"""Focused tests for the Gemini LLM provider (``src.ingestion.enrich``).

Validates the Groq → Gemini migration landed cleanly:
  * ``LLMClient`` Protocol is preserved — ``complete(model, prompt,
    timeout_s) -> str`` — so enrich / compare need no provider branch.
  * The call shape matches google-genai: ``response_mime_type=
    'application/json'`` (the Groq-equivalent JSON mode) is set on
    every call; the pipeline's Pydantic validation sits on top of
    the returned text.
  * Rate-limit detection covers google-genai's ``ClientError`` shape:
    ``code=429`` and / or ``status='RESOURCE_EXHAUSTED'``.
  * Transient (timeout / connection / 5xx) errors retry once;
    non-429 ``ClientError``s (auth, model-not-found, bad prompt) do
    NOT retry — they're permanent for the given inputs.
  * The API key never leaks via ``repr()``.

No real network calls. The ``google.genai`` SDK is imported for
``errors`` + ``types`` so error-class matching uses the real
hierarchy, but ``GeminiClient._client`` is swapped out for a stub.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from google.genai import errors as genai_errors
from google.genai import types as genai_types

from src.ingestion.enrich import GeminiClient, _is_rate_limit_error


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------
@dataclass
class _FakeResponse:
    """Minimal duck-typed GenerateContentResponse — only ``text`` is read."""
    text: str


class _FakeModels:
    """Captures the arguments of generate_content so we can assert on them."""

    def __init__(
        self,
        *,
        response_text: str = "{}",
        raise_exc: BaseException | None = None,
        raise_sequence: list[BaseException | None] | None = None,
    ) -> None:
        self.response_text = response_text
        self.raise_exc = raise_exc
        # raise_sequence lets a test say "fail the first call with X,
        # succeed the second". ``None`` entries mean "succeed with
        # response_text".
        self.raise_sequence = raise_sequence
        self.calls: list[dict] = []

    def generate_content(
        self, *, model: str, contents: Any,
        config: genai_types.GenerateContentConfig | None = None,
    ) -> _FakeResponse:
        self.calls.append({
            "model": model, "contents": contents, "config": config,
        })
        n = len(self.calls)
        if self.raise_sequence is not None:
            idx = n - 1
            if idx < len(self.raise_sequence):
                err = self.raise_sequence[idx]
                if err is not None:
                    raise err
            return _FakeResponse(text=self.response_text)
        if self.raise_exc is not None:
            raise self.raise_exc
        return _FakeResponse(text=self.response_text)


class _FakeClient:
    def __init__(self, models: _FakeModels) -> None:
        self.models = models


def _build_client(models: _FakeModels) -> GeminiClient:
    """Construct a GeminiClient and swap its SDK client for a stub.

    The real ``genai.Client(api_key=...)`` is cheap (no network call
    at init) but we don't need it; swapping ``_client`` keeps tests
    hermetic.
    """
    c = GeminiClient(api_key="test-key-sentinel")
    c._client = _FakeClient(models)  # type: ignore[assignment]
    return c


# ---------------------------------------------------------------------------
# Rate-limit detection — provider-agnostic
# ---------------------------------------------------------------------------
def test_rate_limit_detected_from_genai_client_error_code_429():
    err = genai_errors.ClientError(
        429,
        {"error": {"code": 429, "message": "quota", "status": "RESOURCE_EXHAUSTED"}},
    )
    assert _is_rate_limit_error(err) is True


def test_rate_limit_detected_from_resource_exhausted_status_string():
    # Hypothetical shape where the SDK leaves .code unset but attaches
    # the string status — defence-in-depth.
    class _E(Exception):
        status = "RESOURCE_EXHAUSTED"

    assert _is_rate_limit_error(_E()) is True


def test_rate_limit_detected_from_legacy_status_code_attribute():
    """Backwards-compat with test doubles that mimic the earlier Groq
    SDK's ``status_code`` attribute. The classifier should not care
    which attribute name the SDK uses."""
    class _E(Exception):
        status_code = 429

    assert _is_rate_limit_error(_E()) is True


def test_rate_limit_detected_from_class_name_substring():
    class RateLimitError(Exception):
        pass

    assert _is_rate_limit_error(RateLimitError("too many")) is True


def test_non_429_client_error_is_not_rate_limit():
    err = genai_errors.ClientError(
        401, {"error": {"code": 401, "message": "unauthorized"}},
    )
    assert _is_rate_limit_error(err) is False


def test_plain_exception_is_not_rate_limit():
    assert _is_rate_limit_error(TimeoutError("slow")) is False


# ---------------------------------------------------------------------------
# API key redaction
# ---------------------------------------------------------------------------
def test_api_key_never_leaks_via_repr():
    client = _build_client(_FakeModels(response_text='{"ok": true}'))
    r = repr(client)
    assert "test-key-sentinel" not in r
    assert "REDACTED" in r


def test_api_key_never_leaks_via_str():
    client = _build_client(_FakeModels(response_text='{"ok": true}'))
    assert "test-key-sentinel" not in str(client)


# ---------------------------------------------------------------------------
# Call shape — JSON mode, model, timeout
# ---------------------------------------------------------------------------
def test_complete_forces_json_mime_type():
    """response_mime_type must be 'application/json' — the Gemini
    equivalent of Groq's response_format={'type':'json_object'}. The
    pipeline relies on this to get back parseable JSON."""
    models = _FakeModels(response_text='{"ok": true}')
    client = _build_client(models)
    client.complete(model="gemini-x", prompt="hello", timeout_s=5.0)
    assert len(models.calls) == 1
    cfg = models.calls[0]["config"]
    assert cfg is not None
    assert cfg.response_mime_type == "application/json"


def test_complete_passes_model_and_prompt_through():
    models = _FakeModels(response_text='{"ok": true}')
    client = _build_client(models)
    client.complete(
        model="gemini-2.5-flash-lite", prompt="payload-xyz", timeout_s=5.0,
    )
    assert models.calls[0]["model"] == "gemini-2.5-flash-lite"
    assert models.calls[0]["contents"] == "payload-xyz"


def test_complete_sets_timeout_in_milliseconds():
    """The SDK's HttpOptions.timeout is milliseconds; our pipeline
    passes a float seconds value. Verify the conversion."""
    models = _FakeModels(response_text='{"ok": true}')
    client = _build_client(models)
    client.complete(model="m", prompt="p", timeout_s=12.5)
    http = models.calls[0]["config"].http_options
    assert http is not None
    assert http.timeout == 12500   # 12.5s → 12500ms


def test_complete_returns_response_text_verbatim():
    models = _FakeModels(response_text='{"framing_score": 0.5}')
    client = _build_client(models)
    out = client.complete(model="m", prompt="p", timeout_s=1.0)
    assert out == '{"framing_score": 0.5}'


def test_complete_returns_empty_string_when_response_text_is_none():
    """``resp.text`` can be ``None`` when the SDK had nothing to say;
    the caller json.loads() the result and will raise, which is the
    correct retryable behaviour."""
    class _NoneTextResp:
        text: str | None = None

    class _NoneModels(_FakeModels):
        def generate_content(self, **kw):  # type: ignore[override]
            self.calls.append(kw)
            return _NoneTextResp()  # type: ignore[return-value]

    client = _build_client(_NoneModels())
    assert client.complete(model="m", prompt="p", timeout_s=1.0) == ""


# ---------------------------------------------------------------------------
# Retry policy — one retry on transient, none on 4xx or 429
# ---------------------------------------------------------------------------
def test_rate_limit_error_propagates_without_retry():
    """A 429 must propagate immediately; the orchestrator uses this
    signal as flow-control and would waste budget on a client retry."""
    rate_err = genai_errors.ClientError(
        429,
        {"error": {"code": 429, "message": "quota", "status": "RESOURCE_EXHAUSTED"}},
    )
    models = _FakeModels(raise_exc=rate_err)
    client = _build_client(models)
    with pytest.raises(genai_errors.ClientError):
        client.complete(model="m", prompt="p", timeout_s=1.0)
    # No retry: a single call was issued.
    assert len(models.calls) == 1


def test_non_429_client_error_propagates_without_retry():
    """Auth rejection / bad model id / malformed prompt won't succeed
    on retry with the same inputs — propagate immediately."""
    auth_err = genai_errors.ClientError(
        401, {"error": {"code": 401, "message": "unauthorized"}},
    )
    models = _FakeModels(raise_exc=auth_err)
    client = _build_client(models)
    with pytest.raises(genai_errors.ClientError):
        client.complete(model="m", prompt="p", timeout_s=1.0)
    assert len(models.calls) == 1


def test_model_not_found_404_propagates_without_retry():
    not_found = genai_errors.ClientError(
        404, {"error": {"code": 404, "message": "model not found"}},
    )
    models = _FakeModels(raise_exc=not_found)
    client = _build_client(models)
    with pytest.raises(genai_errors.ClientError):
        client.complete(model="m", prompt="p", timeout_s=1.0)
    assert len(models.calls) == 1


def test_timeout_retries_once_then_succeeds():
    class _MyTimeoutError(Exception):
        pass

    models = _FakeModels(
        response_text='{"ok": true}',
        raise_sequence=[_MyTimeoutError("slow"), None],
    )
    client = _build_client(models)
    out = client.complete(model="m", prompt="p", timeout_s=1.0)
    assert out == '{"ok": true}'
    assert len(models.calls) == 2


def test_connection_error_retries_once_then_succeeds():
    class _ConnectionError(Exception):
        pass

    models = _FakeModels(
        response_text='{"ok": true}',
        raise_sequence=[_ConnectionError("reset"), None],
    )
    client = _build_client(models)
    out = client.complete(model="m", prompt="p", timeout_s=1.0)
    assert out == '{"ok": true}'
    assert len(models.calls) == 2


def test_server_error_5xx_retries_once_then_succeeds():
    server_err = genai_errors.ServerError(
        503, {"error": {"code": 503, "message": "unavailable"}},
    )
    models = _FakeModels(
        response_text='{"ok": true}',
        raise_sequence=[server_err, None],
    )
    client = _build_client(models)
    out = client.complete(model="m", prompt="p", timeout_s=1.0)
    assert out == '{"ok": true}'
    assert len(models.calls) == 2


def test_two_consecutive_transient_errors_propagate_second_one():
    """Only ONE retry — a second transient error must propagate."""
    class _MyTimeoutError(Exception):
        pass

    models = _FakeModels(raise_sequence=[
        _MyTimeoutError("slow-1"), _MyTimeoutError("slow-2"),
    ])
    client = _build_client(models)
    with pytest.raises(_MyTimeoutError, match="slow-2"):
        client.complete(model="m", prompt="p", timeout_s=1.0)
    assert len(models.calls) == 2


def test_non_transient_non_api_error_propagates_immediately():
    """A ValueError (unexpected SDK output, say) is not timeout-shaped
    and not an APIError — propagate without retry."""
    models = _FakeModels(raise_exc=ValueError("boom"))
    client = _build_client(models)
    with pytest.raises(ValueError, match="boom"):
        client.complete(model="m", prompt="p", timeout_s=1.0)
    assert len(models.calls) == 1


# ---------------------------------------------------------------------------
# Provider wiring in run_once
# ---------------------------------------------------------------------------
def test_run_once_imports_gemini_client_not_groq():
    """``run.py`` must import ``GeminiClient`` from enrich, not the
    retired ``GroqClient``. Regression guard against half-finished
    migrations."""
    import src.ingestion.run as run_mod
    assert hasattr(run_mod, "GeminiClient")
    assert not hasattr(run_mod, "GroqClient"), (
        "GroqClient leaked back into src.ingestion.run after migration"
    )


def test_compare_module_reexports_gemini_client():
    """``compare.py`` historically re-exported ``GroqClient`` alongside
    the ``LLMClient`` Protocol. After the migration the re-exported
    name is ``GeminiClient``."""
    import src.ingestion.compare as cmp_mod
    assert hasattr(cmp_mod, "GeminiClient")
    assert not hasattr(cmp_mod, "GroqClient")
