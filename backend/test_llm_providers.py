"""Provider transport and the Gemini -> Groq fallback chain.

Covers what moved out of test_llm.py and test_job_fit.py when the duplicated
transport code was collapsed into one place: client construction, JSON mode,
error classification, and the chain's ordering and reporting.

No test here reaches the network. Providers are stubbed, and the two that do
exercise the real SDK call paths patch the SDK itself.
"""

import pytest

from backend import llm_providers
from backend.llm_providers import (
    ChainResult,
    ProviderResult,
    call_with_fallback,
    classify_error,
    gemini_model_name,
    groq_model_name,
)


@pytest.fixture(autouse=True)
def isolate_provider_env(monkeypatch):
    """Never let a developer's real keys or model overrides affect these tests."""
    for name in ("GEMINI_API_KEY", "GROQ_API_KEY", "GEMINI_MODEL", "GROQ_MODEL"):
        monkeypatch.delenv(name, raising=False)


def ok(text):
    return lambda system, user: ProviderResult(text=text)


def fails(reason):
    return lambda system, user: ProviderResult(error=reason)


# ---------------------------------------------------------------------------
# Model resolution
# ---------------------------------------------------------------------------

def test_models_default_when_unset():
    assert gemini_model_name() == llm_providers.GEMINI_DEFAULT_MODEL
    assert groq_model_name() == llm_providers.GROQ_DEFAULT_MODEL


def test_models_are_overridable(monkeypatch):
    """A retired hosted model must be fixable by configuration, not a code edit."""
    monkeypatch.setenv("GEMINI_MODEL", "gemini-9-flash")
    monkeypatch.setenv("GROQ_MODEL", "llama-99")

    assert gemini_model_name() == "gemini-9-flash"
    assert groq_model_name() == "llama-99"


def test_blank_override_falls_back_to_the_default(monkeypatch):
    """An empty value in .env is 'unset', not 'use the empty string'."""
    monkeypatch.setenv("GEMINI_MODEL", "")
    monkeypatch.setenv("GROQ_MODEL", "")

    assert gemini_model_name() == llm_providers.GEMINI_DEFAULT_MODEL
    assert groq_model_name() == llm_providers.GROQ_DEFAULT_MODEL


# ---------------------------------------------------------------------------
# Error classification
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "message,expected",
    [
        ("Read timeout occurred", "Timeout"),
        ("429 quota exceeded", "Rate limit exceeded"),
        ("rate limit hit", "Rate limit exceeded"),
        ("401 invalid api key", "Authentication error"),
        ("403 forbidden auth", "Authentication error"),
        ("404 NOT_FOUND model retired", "Model unavailable"),
        ("503 UNAVAILABLE high demand", "Service unavailable"),
        ("model is overloaded", "Service unavailable"),
        ("something else entirely", "API error"),
    ],
)
def test_error_classification(message, expected):
    assert classify_error(Exception(message)) == expected


def test_classification_never_returns_raw_provider_text():
    """Status strings reach the user; provider errors can embed URLs and internals."""
    secret = "connection to https://internal.host/v1/key=abc123 failed"

    assert secret not in classify_error(Exception(secret))


# ---------------------------------------------------------------------------
# The chain
# ---------------------------------------------------------------------------

def test_primary_success_reports_plain_success(monkeypatch):
    """Existing callers and the frontend depend on this exact string."""
    monkeypatch.setattr(llm_providers, "PROVIDERS", (("Gemini", ok("payload")),))

    text, outcome = call_with_fallback("sys", "user")

    assert text == "payload"
    assert outcome.status() == "Success"
    assert outcome.provider == "Gemini"
    assert not outcome.used_fallback


def test_falls_back_to_groq_and_says_why(monkeypatch):
    monkeypatch.setattr(
        llm_providers,
        "PROVIDERS",
        (("Gemini", fails("Service unavailable")), ("Groq", ok("payload"))),
    )

    text, outcome = call_with_fallback("sys", "user")

    assert text == "payload"
    assert outcome.provider == "Groq"
    assert outcome.used_fallback
    assert outcome.status() == "Success via Groq (Gemini: Service unavailable)"


def test_groq_is_never_tried_when_gemini_answers(monkeypatch):
    """The fallback must not double the cost of the common case."""
    groq_calls = []

    def groq(system, user):
        groq_calls.append(user)
        return ProviderResult(text="unused")

    monkeypatch.setattr(
        llm_providers, "PROVIDERS", (("Gemini", ok("payload")), ("Groq", groq))
    )

    call_with_fallback("sys", "user")

    assert groq_calls == []


def test_both_failing_reports_both_reasons(monkeypatch):
    monkeypatch.setattr(
        llm_providers,
        "PROVIDERS",
        (("Gemini", fails("Rate limit exceeded")), ("Groq", fails("Authentication error"))),
    )

    text, outcome = call_with_fallback("sys", "user")

    assert text is None
    assert not outcome.ok
    assert outcome.status() == (
        "Failed: Gemini: Rate limit exceeded; Groq: Authentication error"
    )


def test_a_provider_converts_its_own_exceptions(monkeypatch):
    """call_gemini and call_groq must never propagate an SDK exception."""
    monkeypatch.setenv("GEMINI_API_KEY", "k")

    class Boom:
        def __init__(self, *args, **kwargs):
            raise RuntimeError("503 UNAVAILABLE")

    import google.genai

    monkeypatch.setattr(google.genai, "Client", Boom)
    result = llm_providers.call_gemini("sys", "user")

    assert not result.ok
    assert result.error == "Service unavailable"


def test_missing_key_is_reported_per_provider(monkeypatch):
    """With no keys at all, the chain explains that rather than erroring."""
    monkeypatch.setattr(
        llm_providers,
        "PROVIDERS",
        (("Gemini", llm_providers.call_gemini), ("Groq", llm_providers.call_groq)),
    )

    text, outcome = call_with_fallback("sys", "user")

    assert text is None
    assert outcome.status() == "Failed: Gemini: Missing API key; Groq: Missing API key"


# ---------------------------------------------------------------------------
# Validation and retry, applied per provider
# ---------------------------------------------------------------------------

def only_yes(text):
    return {"v": text} if text == "yes" else None


def test_retry_is_attempted_before_moving_to_the_next_provider(monkeypatch):
    calls = []

    def gemini(system, user):
        calls.append(user)
        return ProviderResult(text="yes" if len(calls) == 2 else "no")

    monkeypatch.setattr(llm_providers, "PROVIDERS", (("Gemini", gemini),))

    parsed, outcome = call_with_fallback("sys", "user", retry_prompt="retry", validate=only_yes)

    assert parsed == {"v": "yes"}
    assert calls == ["user", "retry"]
    assert outcome.status() == "Success"


def test_unusable_output_from_primary_moves_to_fallback(monkeypatch):
    """A provider that answers but cannot produce valid output is still a failure."""
    monkeypatch.setattr(
        llm_providers,
        "PROVIDERS",
        (("Gemini", ok("no")), ("Groq", ok("yes"))),
    )

    parsed, outcome = call_with_fallback("sys", "user", retry_prompt="retry", validate=only_yes)

    assert parsed == {"v": "yes"}
    assert "Gemini: Invalid JSON output" in outcome.status()
    assert outcome.provider == "Groq"


def test_chain_result_status_is_stable_for_a_clean_success():
    assert ChainResult(text="x", provider="Gemini").status() == "Success"
