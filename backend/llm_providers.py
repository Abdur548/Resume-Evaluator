"""Provider layer for the optional LLM supplements.

Two things live here and nothing else: how to reach a provider, and what to do
when one fails. Prompts, response schemas, and the PII and prompt-injection
guardrails stay in llm.py and job_fit_llm.py -- a provider never knows it is
looking at a resume.

Why it exists:

- Gemini can fail for reasons a retry will not fix. A model retired for new API
  keys returns 404, a missing or rotated key returns 401/403, and capacity
  spikes return 503. A second provider with its own key and its own model
  covers all three.
- llm.py and job_fit_llm.py previously carried duplicate copies of client
  construction, the retry loop, and the error-classification ladder. They had
  already drifted: one validator gained a type guard the other never got. One
  copy of the transport removes that class of bug.

The chain never raises. Every failure is returned as a status string, because
the deterministic score must reach the user whether or not any provider
answers.
"""

import os
from dataclasses import dataclass

# Both SDKs are imported lazily inside their provider so that an unconfigured
# provider costs nothing at startup and a broken install cannot take down the
# deterministic path.


GEMINI_DEFAULT_MODEL = "gemini-3.7-flash"

# Groq retires hosted models fairly often -- the Llama family this originally
# pointed at is no longer offered. Override with GROQ_MODEL; run
# `python -m backend.llm_providers` to list what the configured key can reach.
#
# Chosen by testing every chat-capable model on the account against this app's
# actual config (temperature 0, JSON mode) and the job-fit schema. gpt-oss-20b
# is faster but silently omits phrasing_suggestions, so it fails validation;
# qwen3.6-27b and groq/compound-mini also pass and are reasonable overrides.
GROQ_DEFAULT_MODEL = "openai/gpt-oss-120b"


@dataclass(frozen=True)
class ProviderResult:
    """Either a provider returned text, or it returned a reason it could not."""

    text: str | None = None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.text is not None


def gemini_model_name() -> str:
    """Resolved per call, since backend/.env loads after this module imports."""
    return os.environ.get("GEMINI_MODEL") or GEMINI_DEFAULT_MODEL


def groq_model_name() -> str:
    return os.environ.get("GROQ_MODEL") or GROQ_DEFAULT_MODEL


def classify_error(error: Exception) -> str:
    """Map a provider exception to a short, caller-safe reason.

    The raw text is deliberately not returned: it reaches the user through the
    status string, and provider errors can embed request URLs and internals.
    """
    message = str(error)
    lowered = message.lower()
    if "timeout" in lowered:
        return "Timeout"
    if "quota" in lowered or "rate" in lowered or "429" in message:
        return "Rate limit exceeded"
    if "api key" in lowered or "auth" in lowered or "401" in message or "403" in message:
        return "Authentication error"
    if "404" in message or "not_found" in lowered or "not found" in lowered:
        return "Model unavailable"
    if "503" in message or "unavailable" in lowered or "overloaded" in lowered:
        return "Service unavailable"
    return "API error"


def call_gemini(system_prompt: str, user_prompt: str) -> ProviderResult:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return ProviderResult(error="Missing API key")

    try:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model=gemini_model_name(),
            contents=user_prompt,
            config=types.GenerateContentConfig(
                temperature=0.0,
                response_mime_type="application/json",
                system_instruction=system_prompt,
            ),
        )
        return ProviderResult(text=response.text)
    except Exception as error:  # noqa: BLE001 - any failure must stay non-fatal
        return ProviderResult(error=classify_error(error))


def call_groq(system_prompt: str, user_prompt: str) -> ProviderResult:
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        return ProviderResult(error="Missing API key")

    try:
        from groq import Groq

        client = Groq(api_key=api_key)
        completion = client.chat.completions.create(
            model=groq_model_name(),
            temperature=0.0,
            # Groq's JSON mode, the counterpart to Gemini's response_mime_type.
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        return ProviderResult(text=completion.choices[0].message.content)
    except Exception as error:  # noqa: BLE001 - any failure must stay non-fatal
        return ProviderResult(error=classify_error(error))


# Ordered: the first entry is primary, the rest are fallbacks tried in turn.
PROVIDERS = (("Gemini", call_gemini), ("Groq", call_groq))


@dataclass(frozen=True)
class ChainResult:
    """What the chain produced, and which provider produced it."""

    text: str | None
    provider: str | None
    # (provider name, reason) for every provider that did not answer.
    failures: tuple[tuple[str, str], ...] = ()

    @property
    def ok(self) -> bool:
        return self.text is not None

    @property
    def used_fallback(self) -> bool:
        return self.ok and bool(self.failures)

    def status(self) -> str:
        """The string shown to the user.

        A primary success stays exactly "Success" so existing callers and the
        frontend are unaffected. A fallback success says so, because the answer
        came from a different model and that is worth knowing.
        """
        if self.ok and not self.failures:
            return "Success"
        if self.ok:
            reasons = "; ".join(f"{name}: {why}" for name, why in self.failures)
            return f"Success via {self.provider} ({reasons})"
        reasons = "; ".join(f"{name}: {why}" for name, why in self.failures)
        return f"Failed: {reasons}"


def call_with_fallback(
    system_prompt: str,
    user_prompt: str,
    retry_prompt: str | None = None,
    validate=None,
) -> tuple[object | None, ChainResult]:
    """Try each provider in order until one returns a response that validates.

    A provider that answers with unusable output gets one retry with
    `retry_prompt` before the chain moves on -- the same retry-once behaviour
    both call sites had, now applied per provider rather than only to Gemini.

    `validate` maps raw text to a parsed object, or None if the text is
    unusable. Returns (validated_object_or_None, ChainResult).
    """
    failures: list[tuple[str, str]] = []

    for name, call in PROVIDERS:
        result = call(system_prompt, user_prompt)

        if result.ok and validate is not None:
            parsed = validate(result.text)
            if parsed is None and retry_prompt is not None:
                retry = call(system_prompt, retry_prompt)
                parsed = validate(retry.text) if retry.ok else None
                if not retry.ok:
                    result = retry
            if parsed is not None:
                return parsed, ChainResult(
                    text=result.text, provider=name, failures=tuple(failures)
                )
            failures.append((name, result.error or "Invalid JSON output"))
            continue

        if result.ok:
            return result.text, ChainResult(
                text=result.text, provider=name, failures=tuple(failures)
            )

        failures.append((name, result.error or "API error"))

    return None, ChainResult(text=None, provider=None, failures=tuple(failures))


def _describe_available_models() -> None:
    """Report which models each configured key can actually reach.

    Hosted model names change; this turns "why did it stop working" into one
    command. Run with: python -m backend.llm_providers
    """
    from . import main  # noqa: F401  -- imported for its backend/.env loading

    print(f"Gemini model configured: {gemini_model_name()}")
    if os.environ.get("GEMINI_API_KEY"):
        try:
            from google import genai

            client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
            names = sorted(
                m.name.removeprefix("models/")
                for m in client.models.list()
                if "generateContent" in (getattr(m, "supported_actions", None) or [])
            )
            print(f"  reachable: {len(names)} models")
            print(f"  configured model available: {gemini_model_name() in names}")
        except Exception as error:  # noqa: BLE001
            print(f"  could not list models: {classify_error(error)}")
    else:
        print("  GEMINI_API_KEY not set")

    print(f"\nGroq model configured: {groq_model_name()}")
    if os.environ.get("GROQ_API_KEY"):
        try:
            from groq import Groq

            names = sorted(m.id for m in Groq(api_key=os.environ["GROQ_API_KEY"]).models.list().data)
            print(f"  reachable: {len(names)} models")
            print(f"  configured model available: {groq_model_name() in names}")
            for name in names:
                print(f"    {name}")
        except Exception as error:  # noqa: BLE001
            print(f"  could not list models: {classify_error(error)}")
    else:
        print("  GROQ_API_KEY not set")


if __name__ == "__main__":
    _describe_available_models()
