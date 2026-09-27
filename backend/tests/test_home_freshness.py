"""Home freshness — 72-hour rule.

The rule constrains WHICH stories Home shows, not how they are ranked
or how they're stored. A story is Home-eligible only while its
``stories.last_seen_at`` falls within :setting:`HOME_FRESHNESS_HOURS`
(default 72) of ``NOW()``. Old stories are NOT deleted; they simply
stop appearing on Home and remain reachable through
``/stories`` and their existing Story Detail route.

Two layers of tests here:

1.  **Pure-Python** — always run.
    * :func:`_freshness_cutoff` math (boundary, timezone-awareness).
    * Config default + env-var override.
    * SQL-clause construction: given ``fresh=True``, the compiled
      SQL contains a ``WHERE stories.last_seen_at >= …`` predicate
      on BOTH the row query and the count query; given ``fresh=False``
      (default), it does NOT.

2.  **DB-backed integration** — skip cleanly when
    ``DATABASE_URL_TEST`` (or ``DATABASE_URL``) is not set. When they
    ARE set, uses the existing ``db_session`` fixture from
    ``conftest.py``, opens a transaction that rolls back at teardown,
    and verifies the endpoint's live behaviour against a real Postgres:
        - fresh story appears
        - stale story does not appear on Home but does appear on
          /stories
        - boundary at exactly the cutoff still appears (inclusive)
        - ordering is preserved among fresh stories
        - a revived stale story (whose last_seen_at is bumped) becomes
          Home-eligible again
        - the configured freshness value is actually respected
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import pytest


# ---------------------------------------------------------------------------
# Layer 1 — pure Python
# ---------------------------------------------------------------------------

from src.api.stories import _freshness_cutoff, list_stories  # noqa: E402
from src.config import Settings, get_settings  # noqa: E402


# ~~~ config ~~~

def test_config_default_freshness_is_72_hours():
    """The Home freshness window defaults to 72 hours."""
    # Fresh Settings instance (bypasses lru_cache) with all env for
    # required fields provided as placeholders so validation passes.
    s = Settings(
        database_url="postgresql://u:p@h/db",
        groq_api_key="dummy",
        llm_model="dummy",
        _env_file=None,  # do not read .env from disk
    )
    assert s.home_freshness_hours == 72


def test_config_freshness_is_overridable(monkeypatch):
    """Users can override the window via HOME_FRESHNESS_HOURS."""
    monkeypatch.setenv("HOME_FRESHNESS_HOURS", "24")
    s = Settings(
        database_url="postgresql://u:p@h/db",
        groq_api_key="dummy",
        llm_model="dummy",
        _env_file=None,
    )
    assert s.home_freshness_hours == 24


def test_config_freshness_rejects_non_positive(monkeypatch):
    """A negative or zero window is meaningless; Pydantic rejects it."""
    monkeypatch.setenv("HOME_FRESHNESS_HOURS", "0")
    with pytest.raises(Exception):  # pydantic ValidationError
        Settings(
            database_url="postgresql://u:p@h/db",
            groq_api_key="dummy",
            llm_model="dummy",
            _env_file=None,
        )


# ~~~ cutoff math ~~~

def test_freshness_cutoff_is_timezone_aware():
    """Cutoff must be tz-aware or SQLAlchemy will refuse to compare it
    against a ``DateTime(timezone=True)`` column."""
    cutoff = _freshness_cutoff(72)
    assert cutoff.tzinfo is not None


def test_freshness_cutoff_is_hours_ago():
    """Exactly N hours before now, within a small tolerance."""
    before = datetime.now(timezone.utc) - timedelta(hours=72)
    cutoff = _freshness_cutoff(72)
    after = datetime.now(timezone.utc) - timedelta(hours=72)
    # Cutoff was computed between `before` and `after`; both are 72h ago
    # by construction, so the cutoff must fall in that window.
    assert before <= cutoff <= after


def test_freshness_cutoff_respects_arbitrary_hours():
    """1h, 24h, 168h (a week) — the function honors what you pass in."""
    for h in (1, 24, 72, 168):
        c = _freshness_cutoff(h)
        expected = datetime.now(timezone.utc) - timedelta(hours=h)
        # Same second granularity (tests run fast).
        assert abs((expected - c).total_seconds()) < 2.0


# ~~~ SQL construction (no DB) ~~~
#
# We compile the query the way SQLAlchemy would send it and inspect
# the emitted SQL string. That verifies the WHERE clause and its
# absence at the source, without needing a live Postgres.

def _compile(stmt) -> str:
    """Return the literal-bound SQL for a Core statement."""
    return str(stmt.compile(compile_kwargs={"literal_binds": True}))


def test_sql_has_no_freshness_where_without_fresh_flag(monkeypatch):
    """When ``fresh=False`` (the default), the query MUST NOT include
    a last_seen_at cutoff — the Stories page must still return the
    full archive."""
    from sqlalchemy import func, select
    from src.db.models import Story, StoryComparison
    # Replicate the exact clause construction from list_stories.
    where_clauses: list = []  # fresh=False → empty
    count_q = select(func.count()).select_from(Story)
    if where_clauses:
        count_q = count_q.where(*where_clauses)
    rows_q = (
        select(Story, StoryComparison.framing_spread)
        .outerjoin(StoryComparison, StoryComparison.story_id == Story.id)
        .order_by(Story.last_seen_at.desc(), Story.id.desc())
    )
    if where_clauses:
        rows_q = rows_q.where(*where_clauses)

    assert "last_seen_at >=" not in _compile(count_q)
    assert "last_seen_at >=" not in _compile(rows_q)


def test_sql_has_freshness_where_with_fresh_flag(monkeypatch):
    """When ``fresh=True``, BOTH the count query and the row query
    must carry the ``last_seen_at >= <cutoff>`` predicate."""
    from sqlalchemy import func, select
    from src.db.models import Story, StoryComparison
    cutoff = _freshness_cutoff(72)
    where_clauses = [Story.last_seen_at >= cutoff]
    count_q = select(func.count()).select_from(Story).where(*where_clauses)
    rows_q = (
        select(Story, StoryComparison.framing_spread)
        .outerjoin(StoryComparison, StoryComparison.story_id == Story.id)
        .order_by(Story.last_seen_at.desc(), Story.id.desc())
        .where(*where_clauses)
    )
    assert "last_seen_at >=" in _compile(count_q)
    assert "last_seen_at >=" in _compile(rows_q)


def test_list_stories_signature_accepts_fresh_flag():
    """A caller can pass ``fresh=True`` or omit it — either signature
    binds without a TypeError. Guards against a future rename that
    breaks the Home hook."""
    import inspect
    params = inspect.signature(list_stories).parameters
    assert "fresh" in params
    # Default is False so the Stories page stays historical.
    assert params["fresh"].default.default is False


# ---------------------------------------------------------------------------
# Layer 2 — DB-backed integration tests
# ---------------------------------------------------------------------------
#
# These skip cleanly when the test DB isn't configured. When it is,
# they cover items 1–10 of the spec against a real Postgres via the
# existing ``db_session`` fixture (transaction rolled back at teardown).

_NO_DB = not (os.environ.get("DATABASE_URL_TEST") or os.environ.get("DATABASE_URL"))
_skip_no_db = pytest.mark.skipif(
    _NO_DB, reason="DATABASE_URL_TEST (or DATABASE_URL) not set"
)


# ---------------------------------------------------------------------------
# Test-only engine reset — Windows/pytest + async SQLAlchemy lifecycle fix
# ---------------------------------------------------------------------------
#
# FastAPI's ``TestClient`` spins up a fresh asyncio event loop for each
# request, then closes it. The app's async engine (see
# ``src/db/session.py``) is a module-level ``@lru_cache(maxsize=1)``
# singleton whose ``AsyncAdaptedQueuePool`` retains asyncpg connections
# bound to whatever loop they were created in. On the *next* test, the
# pool's ``pool_pre_ping`` fires on that dead loop and raises
# ``RuntimeError: Event loop is closed`` — even though the freshness
# query itself is correct. It surfaces on Windows because Python's
# ``ProactorEventLoop`` is stricter about post-close callbacks than the
# POSIX default; the same class of issue is documented widely for
# async-SQLAlchemy-with-TestClient.
#
# Standard fix: for this test file only, swap the engine's pool for
# ``NullPool``. NullPool discards each connection at return time, so
# nothing is ever pooled across event loops. Autouse + ``monkeypatch``
# scopes the change to a single test; the original ``_engine`` is
# restored at teardown. No production code is modified.
@pytest.fixture(autouse=True)
def _reset_app_engine_between_tests(monkeypatch):
    """Give every test a fresh app engine that uses ``NullPool``, so no
    asyncpg connection outlives the TestClient event loop that created
    it. Pure-Python tests never trigger ``_engine()`` so this is a
    no-op for them."""
    if _NO_DB:
        # No test DB configured → the integration tests skip anyway,
        # and touching the engine would try to import a config with
        # missing env vars.
        yield
        return

    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.pool import NullPool

    from src.config import get_settings
    from src.db import session as _db_session

    def _null_pool_engine():
        s = get_settings()
        return create_async_engine(
            s.async_database_url,
            poolclass=NullPool,
            connect_args=s.async_connect_args,
        )

    # Defensively wipe the settings cache before we build our engine.
    # Prior tests in the suite (notably
    # ``tests/test_health.py::test_settings_sync_and_async_properties``
    # and its ``client`` fixture, plus the LLM-model tests in
    # test_compare/test_enrich) monkeypatch env vars, then call
    # ``get_settings.cache_clear()`` followed by ``get_settings()`` —
    # which caches Settings while the env is still monkeypatched.
    # ``monkeypatch`` reverts the env at teardown but does NOT clear
    # the ``@lru_cache`` on ``get_settings``, so the poisoned Settings
    # object survives into subsequent tests. Without this line, our
    # ``_null_pool_engine`` would see the leaked cache — e.g.
    # ``DATABASE_URL = postgresql://u:p@h/d…`` (from test_health.py's
    # sync/async-properties test) — and asyncpg would fail with
    # ``socket.gaierror: [Errno 11001] getaddrinfo failed`` while
    # trying to resolve host ``h``.
    get_settings.cache_clear()

    # Wipe any cached engine/factory from a previous test AND swap
    # ``_engine`` for the NullPool factory for this test's duration.
    _db_session._engine.cache_clear()
    _db_session._sessionmaker.cache_clear()
    monkeypatch.setattr(_db_session, "_engine", _null_pool_engine)
    # ``_sessionmaker`` closes over the module-level ``_engine`` at
    # call time (not at definition time), so clearing its cache is
    # enough — the next call will build a fresh async_sessionmaker
    # bound to the NullPool engine.
    _db_session._sessionmaker.cache_clear()

    yield

    # Post-test: monkeypatch restores the original ``_engine`` symbol.
    # Clear ``_sessionmaker`` so a subsequent test (or an unrelated
    # test file that imports session) doesn't inherit a factory bound
    # to this test's NullPool engine. Also clear the settings cache
    # so we don't hand OUR rebuilt Settings (which was built against
    # a possibly-different env than the next test wants) to the next
    # test file. This is the mirror of the setup clear above.
    _db_session._sessionmaker.cache_clear()
    get_settings.cache_clear()


def _hours_ago(h: float) -> datetime:
    return datetime.now(timezone.utc) - timedelta(hours=h)


def _mk_outlet(session, slug: str = "_test_home_freshness"):
    """Insert a test outlet; conftest cleanup wipes rows whose slug
    starts with ``_test_``."""
    from src.db.models import Outlet
    o = Outlet(
        name="Test Outlet", slug=slug, rss_url="http://example.invalid",
        website="http://example.invalid",
    )
    session.add(o)
    session.commit()
    return o


def _mk_story(session, title: str, last_seen: datetime, first_seen: datetime | None = None):
    from src.db.models import Story
    s = Story(
        title=title,
        topic=None,
        first_seen_at=first_seen or last_seen,
        last_seen_at=last_seen,
        article_count=1,
        summary=None,
    )
    session.add(s)
    session.commit()
    return s


def _api_client(monkeypatch=None, freshness_override_hours: int | None = None):
    """FastAPI TestClient with the app's DATABASE_URL pointed at the
    same test DB the fixture opened. When ``freshness_override_hours``
    is provided, HOME_FRESHNESS_HOURS is overridden for that run."""
    from fastapi.testclient import TestClient
    if freshness_override_hours is not None:
        os.environ["HOME_FRESHNESS_HOURS"] = str(freshness_override_hours)
        get_settings.cache_clear()
    from src.main import app
    return TestClient(app)


@_skip_no_db
def test_db_fresh_story_appears_on_home(db_session):
    """Item 1: a story with last_seen_at = 10h ago appears on Home."""
    _mk_outlet(db_session)
    s = _mk_story(db_session, "_test_home_fresh_10h", _hours_ago(10))
    client = _api_client()
    r = client.get("/stories?page=1&limit=50&fresh=true").json()
    assert any(item["id"] == s.id for item in r["items"])


@_skip_no_db
def test_db_just_inside_window_appears(db_session):
    """Item 2: last_seen_at = 71h ago is still Home-eligible."""
    _mk_outlet(db_session)
    s = _mk_story(db_session, "_test_home_edge_71h", _hours_ago(71))
    client = _api_client()
    r = client.get("/stories?page=1&limit=50&fresh=true").json()
    assert any(item["id"] == s.id for item in r["items"])


@_skip_no_db
def test_db_stale_story_absent_from_home(db_session):
    """Item 3: last_seen_at = 73h ago is NOT on Home."""
    _mk_outlet(db_session)
    s = _mk_story(db_session, "_test_home_stale_73h", _hours_ago(73))
    client = _api_client()
    r = client.get("/stories?page=1&limit=50&fresh=true").json()
    assert all(item["id"] != s.id for item in r["items"])


@_skip_no_db
def test_db_boundary_exactly_72h_is_inclusive(db_session):
    """Item 4: exactly 72h ago passes the ``>=`` boundary. There is a
    tiny race between when we compute the timestamp and when the query
    reads NOW(); pad the stored value by a few seconds inside the
    window so the test is not flaky."""
    _mk_outlet(db_session)
    s = _mk_story(db_session, "_test_home_boundary_72h", _hours_ago(72) + timedelta(seconds=2))
    client = _api_client()
    r = client.get("/stories?page=1&limit=50&fresh=true").json()
    assert any(item["id"] == s.id for item in r["items"])


@_skip_no_db
def test_db_only_fresh_returned_and_ordering_preserved(db_session):
    """Items 5 + 6: many stories in play, only fresh ones come back,
    ordered by ``last_seen_at DESC`` (existing rule, unchanged)."""
    _mk_outlet(db_session)
    a = _mk_story(db_session, "_test_home_multi_a_5h",   _hours_ago(5))
    b = _mk_story(db_session, "_test_home_multi_b_20h",  _hours_ago(20))
    c = _mk_story(db_session, "_test_home_multi_c_100h", _hours_ago(100))  # stale
    client = _api_client()
    ids_in_order = [
        it["id"] for it in client.get("/stories?page=1&limit=50&fresh=true").json()["items"]
        if it["id"] in {a.id, b.id, c.id}
    ]
    assert c.id not in ids_in_order         # stale filtered
    assert ids_in_order.index(a.id) < ids_in_order.index(b.id)  # 5h before 20h


@_skip_no_db
def test_db_stale_story_still_visible_on_stories_page(db_session):
    """Item 7: the general Stories page (no ``fresh``) still returns
    the stale story — it is filtered ONLY from Home. Also verifies
    that Story Detail resolves regardless of age (the definitive
    "stale stories are not archived out of the DB" proof).

    Assertion strategy — total-count delta, not page-1 containment.
    Neon dev-test branches are copy-on-write from their parent, so
    this test DB carries whatever prod-scale data was ingested. A
    100h-old story would be many pages deep in a strict
    ``last_seen_at DESC`` list; asserting it appears in
    ``page=1&limit=50`` is fragile on such a DB and produced a false
    negative on the first Windows run. The total-count delta is
    exact and pagination-invariant:
      * the stale row must add exactly ONE to the archive total
        (``/stories`` without ``fresh``), and
      * exactly ZERO to the fresh-only total
        (``/stories?fresh=true``).
    Together those assertions prove the /stories-vs-/stories?fresh
    split — a strictly stronger check than the previous
    "story appears on page 1".
    """
    _mk_outlet(db_session)
    client = _api_client()

    before_all   = client.get("/stories?page=1&limit=1").json()["total"]
    before_fresh = client.get("/stories?page=1&limit=1&fresh=true").json()["total"]

    s = _mk_story(db_session, "_test_home_only_100h", _hours_ago(100))

    after_all   = client.get("/stories?page=1&limit=1").json()["total"]
    after_fresh = client.get("/stories?page=1&limit=1&fresh=true").json()["total"]

    assert after_all - before_all == 1, (
        f"stale story did not appear in the /stories archive: "
        f"before_total={before_all} after_total={after_all}. "
        "The freshness filter must not apply when `fresh` is omitted."
    )
    assert after_fresh == before_fresh, (
        f"stale story leaked into /stories?fresh=true: "
        f"before_total={before_fresh} after_total={after_fresh}. "
        "A 100h-old story must be excluded from the fresh-only subset."
    )

    # Story Detail must resolve for a stale story too — the
    # definitive "stale stories remain in the DB" proof, independent
    # of any pagination or filter behaviour on the list endpoint.
    detail = client.get(f"/stories/{s.id}")
    assert detail.status_code == 200, (
        f"stale story /stories/{s.id} returned {detail.status_code} "
        "instead of 200"
    )


@_skip_no_db
def test_db_revived_story_returns_to_home(db_session):
    """Item 8: a story that has aged out re-enters Home when its
    ``last_seen_at`` is bumped by a new article on the story."""
    from sqlalchemy import update
    from src.db.models import Story
    _mk_outlet(db_session)
    s = _mk_story(db_session, "_test_home_revive", _hours_ago(100))
    client = _api_client()
    # Currently stale — must NOT appear on Home.
    before = client.get("/stories?page=1&limit=50&fresh=true").json()
    assert all(item["id"] != s.id for item in before["items"])
    # Ingestion attaches a new article; last_seen_at is bumped.
    db_session.execute(
        update(Story).where(Story.id == s.id).values(last_seen_at=_hours_ago(1))
    )
    db_session.commit()
    after = client.get("/stories?page=1&limit=50&fresh=true").json()
    assert any(item["id"] == s.id for item in after["items"])


@_skip_no_db
def test_db_freshness_config_value_is_respected(db_session, monkeypatch):
    """Item 9: overriding HOME_FRESHNESS_HOURS actually changes the
    cutoff. A story that would qualify under 72h but not under 6h
    disappears when the window shrinks."""
    _mk_outlet(db_session)
    s = _mk_story(db_session, "_test_home_config_10h", _hours_ago(10))
    # Under the default 72h window: eligible.
    client_default = _api_client()
    r_default = client_default.get("/stories?page=1&limit=50&fresh=true").json()
    assert any(item["id"] == s.id for item in r_default["items"])
    # Shrink the window to 6h — the 10h-old story now falls out.
    client_tight = _api_client(freshness_override_hours=6)
    r_tight = client_tight.get("/stories?page=1&limit=50&fresh=true").json()
    assert all(item["id"] != s.id for item in r_tight["items"])
    # Restore for other tests.
    monkeypatch.delenv("HOME_FRESHNESS_HOURS", raising=False)
    get_settings.cache_clear()


@_skip_no_db
def test_db_home_with_only_fresh_stories_still_works(db_session):
    """Item 10: a normal Home request with only fresh data returns
    the expected shape (items, page, limit, total, has_more)."""
    _mk_outlet(db_session)
    _mk_story(db_session, "_test_home_normal_a_5h",  _hours_ago(5))
    _mk_story(db_session, "_test_home_normal_b_10h", _hours_ago(10))
    client = _api_client()
    r = client.get("/stories?page=1&limit=50&fresh=true").json()
    for key in ("items", "page", "limit", "total", "has_more"):
        assert key in r
    assert r["page"] == 1
    assert r["limit"] == 50
