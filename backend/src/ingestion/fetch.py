"""RSS fetch + article-text extraction.

Two entry points that the orchestrator calls in order:

    discover_articles(session, outlet) -> list[Article]
        Walks the outlet's RSS feed, drops URLs already in `articles`,
        inserts new rows with processing_state='discovered' + best-effort
        metadata (headline, published_at, author).

    extract_articles(session) -> tuple[int, int]
        Picks up rows in state 'discovered', downloads each URL, extracts
        the main body via trafilatura, advances to 'extracted' or (after
        the documented 3-failure limit) 'failed_extract'. Returns
        (extracted, failed) counts.

Architecture §10 state machine — every transition happens through
`_advance_state` so the state, timestamp, error, and attempt_count stay
consistent, and it is safe to rerun.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Iterable, Protocol

import feedparser
import httpx
import trafilatura
from dateutil import parser as date_parser
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from src.db.models import Article, Outlet

log = logging.getLogger(__name__)

# Documented retry cap (Appendix A: "after 3 failures it moves to
# `failed_analyze` and won't be retried automatically"). The same cap
# applies to extract/embed steps.
MAX_ATTEMPTS = 3

DEFAULT_USER_AGENT = (
    "NewsLens/0.1 (MCA project; +https://github.com/newslens/newslens) "
    "python-httpx"
)

# Extraction failure states, keyed by the pipeline stage.
FAILED_STATE = {
    "discovered": "failed_extract",
    "extracted": "failed_embed",
    "clustered": "failed_analyze",
}


class HttpFetcher(Protocol):
    """A minimal fetcher interface so tests can inject a fake."""
    def get(self, url: str, *, timeout: float = ...) -> httpx.Response: ...


@dataclass
class HttpxFetcher:
    """Default fetcher: httpx with a polite UA + reasonable timeout.

    Instance-scoped so a single client is reused across an ingestion cycle
    (connection pooling, HTTP/2 where the server supports it).
    """

    user_agent: str = DEFAULT_USER_AGENT
    timeout_s: float = 20.0
    _client: httpx.Client | None = None

    def __post_init__(self) -> None:
        self._client = httpx.Client(
            headers={"User-Agent": self.user_agent, "Accept": "*/*"},
            follow_redirects=True,
            timeout=self.timeout_s,
        )

    def get(self, url: str, *, timeout: float | None = None) -> httpx.Response:
        assert self._client is not None
        return self._client.get(url, timeout=timeout or self.timeout_s)

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None


# =============================================================================
# RSS discovery
# =============================================================================
@dataclass
class DiscoveredEntry:
    url: str
    headline: str
    author: str | None
    published_at: datetime


def parse_feed(feed_bytes: bytes | str) -> list[DiscoveredEntry]:
    """Parse an RSS/Atom feed into DiscoveredEntry list.

    Ignores entries that lack a URL, headline, or a parseable published
    date. Any published date without tzinfo is treated as UTC (feedparser
    already normalizes most feeds to UTC via `published_parsed`).
    """
    parsed = feedparser.parse(feed_bytes)
    out: list[DiscoveredEntry] = []
    for entry in parsed.entries:
        url = (entry.get("link") or "").strip()
        headline = (entry.get("title") or "").strip()
        if not url or not headline:
            continue

        published_at: datetime | None = None
        if entry.get("published_parsed"):
            import time
            ts = time.mktime(entry.published_parsed)
            published_at = datetime.fromtimestamp(ts, tz=timezone.utc)
        elif entry.get("published"):
            try:
                published_at = date_parser.parse(entry.published)
                if published_at.tzinfo is None:
                    published_at = published_at.replace(tzinfo=timezone.utc)
            except (ValueError, TypeError):
                published_at = None

        if published_at is None:
            # Some feeds omit dates; skip rather than fabricate a timestamp.
            continue

        author = (entry.get("author") or "").strip() or None
        out.append(
            DiscoveredEntry(
                url=url,
                headline=headline[:1000],
                author=author,
                published_at=published_at,
            )
        )
    return out


def discover_articles(
    session: Session,
    outlet: Outlet,
    *,
    fetcher: HttpFetcher,
) -> int:
    """Fetch the outlet's RSS feed, insert new URLs as `discovered`.

    Returns the number of new articles inserted (URL-deduped).
    """
    log.info("discover: outlet=%s rss=%s", outlet.slug, outlet.rss_url)
    try:
        resp = fetcher.get(outlet.rss_url)
    except Exception as exc:
        log.warning("discover: fetch failed for %s: %s", outlet.slug, exc)
        return 0
    if resp.status_code != 200:
        log.warning("discover: HTTP %s for %s", resp.status_code, outlet.slug)
        return 0

    entries = parse_feed(resp.content)
    log.info("discover: %d entries from %s", len(entries), outlet.slug)
    if not entries:
        return 0

    # URL-deduped insert. Rely on the UNIQUE(articles.url) index +
    # ON CONFLICT DO NOTHING so concurrent runs are safe.
    inserted = 0
    for entry in entries:
        stmt = (
            pg_insert(Article)
            .values(
                outlet_id=outlet.id,
                url=entry.url,
                headline=entry.headline,
                author=entry.author,
                published_at=entry.published_at,
                processing_state="discovered",
            )
            .on_conflict_do_nothing(index_elements=["url"])
            .returning(Article.id)
        )
        result = session.execute(stmt).first()
        if result is not None:
            inserted += 1
    session.commit()
    log.info("discover: %d new articles for %s", inserted, outlet.slug)
    return inserted


# =============================================================================
# Article extraction (state machine driver)
# =============================================================================
def _advance_state(
    session: Session,
    article_id: int,
    *,
    new_state: str,
    error: str | None = None,
    reset_attempts: bool = False,
) -> None:
    """Move one article to `new_state`, stamp state_updated_at, set error.

    reset_attempts=True zeroes attempt_count on a successful transition;
    otherwise it is left untouched.
    """
    values: dict = {
        "processing_state": new_state,
        "state_updated_at": datetime.now(tz=timezone.utc),
        "state_error": error,
    }
    if reset_attempts:
        values["attempt_count"] = 0
    session.execute(
        update(Article).where(Article.id == article_id).values(**values)
    )


def _record_failure(
    session: Session,
    article: Article,
    stage_from: str,
    error: str,
) -> None:
    """Bump attempt_count. On the 3rd failure, move to the stage's failed_ state.

    Never commits on its own — the caller controls the transaction.
    """
    new_attempts = (article.attempt_count or 0) + 1
    failed_state = FAILED_STATE.get(stage_from, "failed_analyze")

    if new_attempts >= MAX_ATTEMPTS:
        log.warning(
            "extract: %d attempts on article_id=%s → moving to %s",
            new_attempts, article.id, failed_state,
        )
        session.execute(
            update(Article)
            .where(Article.id == article.id)
            .values(
                processing_state=failed_state,
                state_updated_at=datetime.now(tz=timezone.utc),
                state_error=error[:2000],
                attempt_count=new_attempts,
            )
        )
    else:
        # Stay in the same state; next run will retry.
        log.info(
            "extract: attempt %d/%d on article_id=%s failed: %s",
            new_attempts, MAX_ATTEMPTS, article.id, error[:120],
        )
        session.execute(
            update(Article)
            .where(Article.id == article.id)
            .values(
                state_updated_at=datetime.now(tz=timezone.utc),
                state_error=error[:2000],
                attempt_count=new_attempts,
            )
        )


def _extract_one(article: Article, resp: httpx.Response) -> str | None:
    """Trafilatura → main body text, or None if extraction fails."""
    if not resp.text:
        return None
    text = trafilatura.extract(
        resp.text,
        include_comments=False,
        include_tables=False,
        favor_recall=True,
        url=article.url,
    )
    if text is None:
        return None
    text = text.strip()
    return text or None


def extract_articles(
    session: Session,
    *,
    fetcher: HttpFetcher,
    batch_limit: int = 100,
) -> tuple[int, int]:
    """Advance up to `batch_limit` articles from `discovered` to `extracted`.

    Returns (extracted, failed) — failed counts only rows that hit the
    3-failure cap this run.
    """
    q = (
        select(Article)
        .where(Article.processing_state == "discovered")
        .order_by(Article.id)
        .limit(batch_limit)
    )
    articles = list(session.scalars(q))
    if not articles:
        return 0, 0

    log.info("extract: %d candidates in state=discovered", len(articles))
    extracted = 0
    failed = 0

    for article in articles:
        try:
            resp = fetcher.get(article.url)
            if resp.status_code != 200:
                _record_failure(
                    session, article, "discovered",
                    f"HTTP {resp.status_code}",
                )
                if (article.attempt_count or 0) + 1 >= MAX_ATTEMPTS:
                    failed += 1
                session.commit()
                continue

            text = _extract_one(article, resp)
            if not text:
                _record_failure(
                    session, article, "discovered",
                    "trafilatura returned no text",
                )
                if (article.attempt_count or 0) + 1 >= MAX_ATTEMPTS:
                    failed += 1
                session.commit()
                continue

            session.execute(
                update(Article)
                .where(Article.id == article.id)
                .values(
                    full_text=text,
                    processing_state="extracted",
                    state_updated_at=datetime.now(tz=timezone.utc),
                    state_error=None,
                    attempt_count=0,  # reset on success (per stage)
                )
            )
            extracted += 1
            session.commit()

        except Exception as exc:
            _record_failure(session, article, "discovered", f"{type(exc).__name__}: {exc}")
            if (article.attempt_count or 0) + 1 >= MAX_ATTEMPTS:
                failed += 1
            session.commit()

    log.info("extract: extracted=%d failed=%d", extracted, failed)
    return extracted, failed
