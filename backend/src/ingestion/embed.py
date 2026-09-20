"""MiniLM sentence-transformer embeddings for extracted articles.

Advances rows from `extracted` to `embedded`. Vectors are 384-dim (matches
`articles.embedding VECTOR(384)`) and stored via pgvector.

Design note: an `Embedder` protocol sits between the pipeline and the
model implementation so:
  - Production runs use `MiniLMEmbedder` (sentence-transformers, local
    model download the first time — 90MB, cached under HF_HOME).
  - Tests use `HashEmbedder`, a deterministic 384-dim vector derived from
    a text hash. Same interface, no model download, ~microsecond per call.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from typing import Protocol, Sequence

import numpy as np
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from src.db.models import Article

log = logging.getLogger(__name__)

EMBED_DIM = 384
DEFAULT_MODEL = "sentence-transformers/all-MiniLM-L6-v2"


class Embedder(Protocol):
    dim: int
    def encode(self, texts: Sequence[str]) -> np.ndarray: ...


class MiniLMEmbedder:
    """Wraps sentence-transformers/all-MiniLM-L6-v2.

    Lazily imports sentence_transformers so environments without the
    package (or without the model download available) can still import
    this module.
    """

    dim = EMBED_DIM

    def __init__(self, model_name: str = DEFAULT_MODEL) -> None:
        from sentence_transformers import SentenceTransformer  # local
        self._model = SentenceTransformer(model_name)

    def encode(self, texts: Sequence[str]) -> np.ndarray:
        vecs = self._model.encode(list(texts), convert_to_numpy=True,
                                  normalize_embeddings=True)
        return np.asarray(vecs, dtype=np.float32)


class HashEmbedder:
    """Deterministic, dependency-free embedder for tests and CI.

    Maps each text to a normalized 384-dim vector by hashing tokens into
    buckets. Similar texts (overlapping vocabulary) get similar vectors,
    so pgvector cosine similarity still exercises meaningful thresholds.
    Not a real model — DO NOT use in production.
    """

    dim = EMBED_DIM

    def __init__(self, dim: int = EMBED_DIM) -> None:
        self.dim = dim

    def encode(self, texts: Sequence[str]) -> np.ndarray:
        rows = np.zeros((len(texts), self.dim), dtype=np.float32)
        for i, text in enumerate(texts):
            # tokenize on whitespace + lowercase, hash into buckets
            for tok in (text or "").lower().split():
                h = hashlib.md5(tok.encode("utf-8")).digest()
                idx = int.from_bytes(h[:4], "little") % self.dim
                # sign from second nibble → shape is not just presence
                sign = 1.0 if h[4] & 1 else -1.0
                rows[i, idx] += sign
            norm = float(np.linalg.norm(rows[i]))
            if norm > 0:
                rows[i] /= norm
        return rows


def embed_articles(
    session: Session,
    *,
    embedder: Embedder,
    batch_limit: int = 100,
) -> int:
    """Advance up to `batch_limit` articles from extracted → embedded.

    Returns number of articles embedded this call.
    """
    if embedder.dim != EMBED_DIM:
        raise ValueError(f"Embedder must produce {EMBED_DIM}-dim vectors, "
                         f"got {embedder.dim}")

    q = (
        select(Article)
        .where(Article.processing_state == "extracted")
        .order_by(Article.id)
        .limit(batch_limit)
    )
    articles = list(session.scalars(q))
    if not articles:
        return 0

    log.info("embed: %d candidates in state=extracted", len(articles))

    # Embed headline + first 2000 chars of body — plenty for a topic-level
    # semantic signal, keeps token counts predictable across long articles.
    def _text(a: Article) -> str:
        body = (a.full_text or "")[:2000]
        return f"{a.headline}\n\n{body}".strip()

    texts = [_text(a) for a in articles]
    vecs = embedder.encode(texts)

    now = datetime.now(tz=timezone.utc)
    for article, vec in zip(articles, vecs):
        session.execute(
            update(Article)
            .where(Article.id == article.id)
            .values(
                embedding=vec.tolist(),
                processing_state="embedded",
                state_updated_at=now,
                state_error=None,
                attempt_count=0,
            )
        )
    session.commit()
    log.info("embed: %d articles embedded", len(articles))
    return len(articles)
