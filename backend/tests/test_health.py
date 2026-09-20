"""Smoke test: /health returns 200 without touching the database.

Uses a monkeypatched environment so importing src.main does not require a
real DATABASE_URL, GROQ_API_KEY, or LLM_MODEL at CI startup.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://x:y@localhost/x")
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    monkeypatch.setenv("LLM_MODEL", "test-model")
    monkeypatch.setenv("CORS_ORIGINS", "http://localhost:5173")

    # Clear cached settings so the fixture-provided env is picked up.
    from src.config import get_settings

    get_settings.cache_clear()

    from src.main import app

    return TestClient(app)


def test_health(client: TestClient) -> None:
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
