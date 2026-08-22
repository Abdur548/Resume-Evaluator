"""Test-wide isolation from real LLM providers.

backend/main.py loads backend/.env at import, which is correct for running the
app and wrong for running the tests: with a real key present the suite started
making live API calls. That made it slow (84s versus 4s), dependent on network
and provider availability, non-deterministic where a test compared two results,
and quietly billable.

Tests that exercise provider behaviour stub it explicitly. Nothing should reach
a real provider by accident, so the keys are cleared for every test. A test
that wants a provider sets its own key with monkeypatch, which applies after
this fixture.
"""

import pytest

PROVIDER_ENV_VARS = (
    "GEMINI_API_KEY",
    "GROQ_API_KEY",
    "GEMINI_MODEL",
    "GROQ_MODEL",
)


@pytest.fixture(autouse=True)
def no_real_llm_calls(monkeypatch):
    for name in PROVIDER_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
