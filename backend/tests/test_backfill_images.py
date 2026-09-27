"""Behavioural tests for the image-backfill script.

The backfill's SQL is exercised via the real db_session fixture from
conftest.py (which skips gracefully when DATABASE_URL_TEST is unset),
while a FakeFetcher stands in for the network so the test never
reaches a live outlet.

We test the outcomes that matter to the design brief:

  1. Only rows with image_url IS NULL are visited.
  2. A row that already has an image is NOT refetched.
  3. HTTP failures and parse failures are logged and skipped, never
     raised; the loop moves on.
  4. Successful extraction writes only image_url (never disturbs
     processing_state / attempt_count / anything else).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.orm import sessionmaker

from src.db.models import Article, Outlet
from src.ingestion.backfill_images import backfill_images

from tests.conftest import FakeResponse


class RecordingFetcher:
    """Fetcher that records the URLs it was asked to fetch.

    Response is picked from `responses` dict; missing URLs return 404.
    Exceptions can be injected via `raise_for`.
    """
    def __init__(self, responses=None, raise_for=None):
        self.responses = responses or {}
        self.raise_for = raise_for or {}
        self.calls: list[str] = []

    def get(self, url, *, timeout=None):
        self.calls.append(url)
        if url in self.raise_for:
            raise self.raise_for[url]
        return self.responses.get(url, FakeResponse(404, b"", url))

    def close(self):
        pass


def _make_article(session, outlet, url, image_url=None):
    now = datetime.now(tz=timezone.utc)
    a = Article(
        outlet_id=outlet.id, url=url,
        headline="_test bf article",
        author=None,
        published_at=now - timedelta(hours=1),
        full_text="body " * 10,
        processing_state="complete",
        image_url=image_url,
    )
    session.add(a)
    session.flush()
    return a


@pytest.fixture()
def bf_outlet(db_session):
    o = Outlet(name="_test bf outlet", slug="_test_bf_o",
               rss_url="https://x.example/_test_bf_o",
               website="https://x.example", active=True)
    db_session.add(o)
    db_session.flush()
    return o


def _session_factory(db_session):
    """Bind a sessionmaker onto the same connection the fixture uses.

    The backfill takes a session_factory; we hand it one that reuses
    the fixture's connection so writes are visible to the fixture and
    roll back at teardown.
    """
    return sessionmaker(bind=db_session.connection(), expire_on_commit=False)


def _html_with_og(url):
    return (
        "<html><head><title>t</title>"
        f'<meta property="og:image" content="{url}" />'
        "</head><body>body</body></html>"
    )


def test_backfill_only_visits_null_image_rows(db_session, bf_outlet):
    a_null = _make_article(db_session, bf_outlet, "https://x.example/a")
    a_has  = _make_article(db_session, bf_outlet, "https://x.example/b",
                           image_url="https://x.example/existing.jpg")
    db_session.commit()

    fetcher = RecordingFetcher(responses={
        "https://x.example/a": FakeResponse(
            200, _html_with_og("https://cdn.example/new.jpg"),
            "https://x.example/a",
        ),
    })
    stats = backfill_images(
        limit=10, sleep_s=0.0,
        outlet_slug=bf_outlet.slug,
        fetcher=fetcher,
        session_factory=_session_factory(db_session),
    )
    # Only the NULL row was fetched.
    assert fetcher.calls == ["https://x.example/a"]
    assert stats.updated == 1

    # The already-populated row is untouched.
    db_session.refresh(a_has)
    assert a_has.image_url == "https://x.example/existing.jpg"
    # And the null row now has the extracted image.
    db_session.refresh(a_null)
    assert a_null.image_url == "https://cdn.example/new.jpg"


def test_backfill_http_failure_is_swallowed(db_session, bf_outlet):
    a = _make_article(db_session, bf_outlet, "https://x.example/broken")
    db_session.commit()

    fetcher = RecordingFetcher(
        raise_for={"https://x.example/broken": ConnectionError("dns fail")}
    )
    stats = backfill_images(
        limit=10, sleep_s=0.0,
        outlet_slug=bf_outlet.slug,
        fetcher=fetcher,
        session_factory=_session_factory(db_session),
    )
    assert stats.scanned == 1
    assert stats.updated == 0
    assert stats.http_failed == 1
    # Row is still NULL and unchanged.
    db_session.refresh(a)
    assert a.image_url is None


def test_backfill_no_image_found_marks_no_image(db_session, bf_outlet):
    a = _make_article(db_session, bf_outlet, "https://x.example/plain")
    db_session.commit()

    fetcher = RecordingFetcher(responses={
        "https://x.example/plain": FakeResponse(
            200, "<html><head></head><body>no meta</body></html>",
            "https://x.example/plain",
        ),
    })
    stats = backfill_images(
        limit=10, sleep_s=0.0,
        outlet_slug=bf_outlet.slug,
        fetcher=fetcher,
        session_factory=_session_factory(db_session),
    )
    assert stats.no_image == 1
    assert stats.updated == 0
    db_session.refresh(a)
    assert a.image_url is None


def test_backfill_preserves_processing_state(db_session, bf_outlet):
    a = _make_article(db_session, bf_outlet, "https://x.example/keep-state")
    original_state = a.processing_state
    original_attempts = a.attempt_count
    db_session.commit()

    fetcher = RecordingFetcher(responses={
        "https://x.example/keep-state": FakeResponse(
            200, _html_with_og("https://cdn.example/ok.jpg"),
            "https://x.example/keep-state",
        ),
    })
    backfill_images(
        limit=10, sleep_s=0.0,
        outlet_slug=bf_outlet.slug,
        fetcher=fetcher,
        session_factory=_session_factory(db_session),
    )
    db_session.refresh(a)
    assert a.processing_state == original_state
    assert a.attempt_count == original_attempts
    assert a.image_url == "https://cdn.example/ok.jpg"
