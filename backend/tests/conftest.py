"""Test fixtures shared across the ingestion test suite.

The DB fixture requires a real PostgreSQL with the vector extension —
the schema alone is what's under test, and there is no substitute that
supports pgvector, ivfflat, TSVECTOR generated columns, and the
outlet_30d_stats materialized view together.

The fixture expects DATABASE_URL_TEST to point at a Postgres database
you can safely wipe between tests. In local dev, that is the
`newslens_test` DB in the container / your machine. In CI (e.g. GitHub
Actions), spin up a Postgres service and set DATABASE_URL_TEST to it.

If DATABASE_URL_TEST is not set, DB-touching tests are SKIPPED — pure
unit tests still run.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker


def _test_url() -> str | None:
    return os.environ.get("DATABASE_URL_TEST") or os.environ.get("DATABASE_URL")


@pytest.fixture(scope="session")
def db_url() -> str:
    url = _test_url()
    if not url:
        pytest.skip("DATABASE_URL_TEST (or DATABASE_URL) not set")
    # Rewrite asyncpg → psycopg for these sync tests
    return url.replace("+asyncpg", "+psycopg") if "+asyncpg" in url else url


@pytest.fixture(scope="session")
def engine(db_url):
    eng = create_engine(db_url, pool_pre_ping=True)
    # Sanity-check that the schema is present.
    with eng.connect() as conn:
        try:
            conn.execute(text("SELECT 1 FROM outlets LIMIT 0"))
        except Exception as exc:
            pytest.skip(f"schema missing on test DB: {exc}. "
                        f"Run `alembic upgrade head` against DATABASE_URL_TEST.")
    yield eng
    eng.dispose()


@pytest.fixture()
def db_session(engine) -> Session:
    """Per-test session with an outer transaction that rolls back at end.

    Every test can INSERT freely without polluting the DB — the
    connection is dropped at teardown, undoing everything.
    """
    Session_ = sessionmaker(bind=engine, expire_on_commit=False)
    session = Session_()
    try:
        yield session
    finally:
        session.rollback()
        # Also purge any _test_* rows from prior interrupted runs.
        # Cleanup order matters (dependents before parents; RESTRICT FK
        # on articles.outlet_id). We identify test-owned outlets by slug
        # pattern; the orchestrator test uses 'the-hindu' so we include
        # it too (any real ingestion state on the shared dev DB has
        # already been rolled back or lived in a separate DB anyway).
        session.execute(text("""
            WITH test_outlets AS (
                SELECT id FROM outlets
                 WHERE slug LIKE '_test_%' OR slug='the-hindu'
            ),
            test_articles AS (
                SELECT id FROM articles
                 WHERE outlet_id IN (SELECT id FROM test_outlets)
                    OR url LIKE '_test_%'
            ),
            test_stories AS (
                SELECT id FROM stories
                 WHERE title LIKE '_test_%'
                    OR title LIKE '_dbg_%'
            )
            DELETE FROM article_analysis
             WHERE article_id IN (SELECT id FROM test_articles);
        """))
        session.execute(text("""
            DELETE FROM eval_labels
             WHERE article_id IN (
               SELECT id FROM articles
                WHERE outlet_id IN (
                  SELECT id FROM outlets
                   WHERE slug LIKE '_test_%' OR slug='the-hindu'
                ) OR url LIKE '_test_%');
            DELETE FROM story_overrides
             WHERE article_id IN (
               SELECT id FROM articles
                WHERE outlet_id IN (
                  SELECT id FROM outlets
                   WHERE slug LIKE '_test_%' OR slug='the-hindu'
                ) OR url LIKE '_test_%')
                OR forced_story_id IN (
                  SELECT id FROM stories
                   WHERE title LIKE '_test_%' OR title LIKE '_dbg_%');
            DELETE FROM story_comparisons
             WHERE story_id IN (
               SELECT id FROM stories
                WHERE title LIKE '_test_%' OR title LIKE '_dbg_%');
            DELETE FROM articles
             WHERE outlet_id IN (
               SELECT id FROM outlets
                WHERE slug LIKE '_test_%' OR slug='the-hindu'
             ) OR url LIKE '_test_%';
            DELETE FROM stories
             WHERE title LIKE '_test_%' OR title LIKE '_dbg_%';
            DELETE FROM outlets
             WHERE slug LIKE '_test_%' OR slug='the-hindu';
            -- ingestion_runs rows from tests accumulate; they carry no
            -- reference to test data and are harmless. Purge periodically
            -- by hand if desired.
        """))
        session.commit()
        session.close()


class FakeResponse:
    """Minimal duck-typed httpx.Response for the fetcher protocol."""
    def __init__(self, status_code: int, content: bytes | str, url: str = ""):
        self.status_code = status_code
        if isinstance(content, str):
            self.content = content.encode("utf-8")
            self.text = content
        else:
            self.content = content
            self.text = content.decode("utf-8", errors="replace")
        self.url = url


class FakeFetcher:
    """In-memory HTTP fetcher: URL → FakeResponse, with fail-injection."""

    def __init__(self, responses: dict[str, FakeResponse] | None = None,
                 raise_for: dict[str, Exception] | None = None):
        self.responses = responses or {}
        self.raise_for = raise_for or {}
        self.calls: list[str] = []

    def get(self, url: str, *, timeout: float | None = None):
        self.calls.append(url)
        if url in self.raise_for:
            raise self.raise_for[url]
        if url in self.responses:
            return self.responses[url]
        return FakeResponse(404, b"", url)

    def close(self) -> None:
        pass


def make_rss(items: list[dict]) -> str:
    """Build a minimal RSS 2.0 document for tests."""
    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<rss version="2.0"><channel><title>test feed</title>',
    ]
    for it in items:
        pub = it.get("pubDate",
                     datetime.now(tz=timezone.utc).strftime("%a, %d %b %Y %H:%M:%S +0000"))
        author = it.get("author", "")
        parts.append(
            "<item>"
            f"<title>{it['title']}</title>"
            f"<link>{it['link']}</link>"
            f"<pubDate>{pub}</pubDate>"
            + (f"<author>{author}</author>" if author else "")
            + "</item>"
        )
    parts.append("</channel></rss>")
    return "".join(parts)


def make_article_html(headline: str, body: str) -> str:
    """Build an HTML page trafilatura can extract."""
    return f"""<!doctype html><html><head><title>{headline}</title></head>
<body>
  <article>
    <h1>{headline}</h1>
    <p>{body}</p>
  </article>
</body></html>"""


@pytest.fixture()
def fake_fetcher():
    """A blank FakeFetcher; tests fill in responses as needed."""
    return FakeFetcher()
