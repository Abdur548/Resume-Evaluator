import os
import re
import json
from google import genai
from google.genai import types


MODEL_NAME = "gemini-2.5-flash"

# Instruction-shaped patterns only.
#
# An earlier version matched the bare word "bypass" and a bare "system:"
# anywhere in the text. Both are ordinary vocabulary in security and
# engineering resumes -- "prevented authentication bypass", "System: designed a
# queue" -- so the guardrail silently disabled the LLM supplement for exactly
# the candidates the Cybersecurity Analyst profile is meant to serve.
#
# These require a verb aimed at instructions or a role reassignment, which is
# what an injection attempt looks like and what ordinary resume prose does not.
# Regex is a secondary signal here; the primary defense is the system prompt's
# instruction to treat resume and job-description text as untrusted data.
INJECTION_TARGET = r"(?:instructions?|rules?|guardrails?|restrictions?|constraints?|prompts?|directives?|safety\s+\w+)"

INJECTION_PATTERNS = [
    # "ignore / disregard / forget / override (all your previous) instructions"
    rf"(?i)\b(?:ignore|disregard|forget|override|discard)\b[^.\n]{{0,40}}?\b{INJECTION_TARGET}\b",
    # "bypass the safety rules" -- but not "prevented an authentication bypass"
    rf"(?i)\bbypass(?:ing)?\b[^.\n]{{0,40}}?\b{INJECTION_TARGET}\b",
    # Role reassignment: "you are now a recruiter who...", "act as an evaluator"
    r"(?i)\byou\s+are\s+now\s+(?:a|an|the)\b",
    r"(?i)\b(?:act|behave|respond)\s+as\s+(?:a|an|the)\b[^.\n]{0,30}\b(?:assistant|model|ai|system)\b",
    # A fake conversation turn at the start of a line. "assistant:" and "user:"
    # essentially never open a resume line, so they stand alone; "System:" does
    # ("System: designed a distributed queue"), so it additionally requires an
    # instruction cue rather than ordinary descriptive prose.
    r"(?im)^\s*(?:assistant|user)\s*:",
    r"(?im)^\s*system\s*:\s*(?=[^\n]*\b(?:you|your|must|always|never|ignore|"
    r"override|disregard|return|output|respond|reply|score|rate|say|print)\b)",
    # Explicit output hijacking
    r"(?i)\b(?:new|updated|revised)\s+(?:instructions?|system\s+prompt)\b",
    r"(?i)\bprint\s+(?:your|the)\s+(?:system\s+prompt|instructions)\b",
]


def detect_prompt_injection(text: str) -> bool:
    return any(re.search(pattern, text) for pattern in INJECTION_PATTERNS)

def mask_pii(text: str) -> str:
    # Phone numbers
    phone_pattern = r"\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}"
    text = re.sub(phone_pattern, "[REDACTED]", text)
    
    # SSN or national ID (###-##-####)
    ssn_pattern = r"\b\d{3}-\d{2}-\d{4}\b"
    text = re.sub(ssn_pattern, "[REDACTED]", text)
    
    # Full addresses roughly: digits followed by words and a common street suffix
    address_pattern = r"\b\d+\s+[A-Za-z0-9\s.,]+(?:Street|St|Avenue|Ave|Road|Rd|Boulevard|Blvd|Lane|Ln|Drive|Dr|Court|Ct)\b"
    text = re.sub(address_pattern, "[REDACTED]", text, flags=re.IGNORECASE)
    
    return text

def validate_llm_response(response_text: str) -> dict | None:
    if not response_text:
        return None
    try:
        # Strip markdown json blocks if present
        cleaned = re.sub(r"```json\s*", "", response_text)
        cleaned = re.sub(r"```\s*$", "", cleaned)
        data = json.loads(cleaned)

        # A JSON array or scalar is valid JSON but has no .keys(); calling it
        # raised an AttributeError that surfaced to the user as a spurious
        # "API Error". The job-fit validator has always guarded this.
        if not isinstance(data, dict):
            return None

        required_keys = {"field_relevance", "structure", "parseability", "impact"}
        if not required_keys.issubset(data.keys()):
            return None

        # Enforce integers 0-100. bool is a subclass of int, so `True` would
        # otherwise validate as a score and render in the UI as "true / 100".
        for k in required_keys:
            val = data[k]
            if isinstance(val, bool) or not isinstance(val, int):
                return None
            if not (0 <= val <= 100):
                return None

        # Only return the specific required categories, ignore extra keys if any
        return {k: data[k] for k in required_keys}
    except (json.JSONDecodeError, TypeError):
        return None

def get_llm_evaluation(text: str, field: str, heuristic_result: dict) -> tuple[dict | None, str]:
    # 4. BEHAVIORAL / FALLBACK GUARDRAIL (Empty/short/broken text)
    if len(text.split()) < 50:
        return None, "Skipped: Resume text is too short or empty"
        
    # Check parseability heuristically
    try:
        sections = heuristic_result.get("categories", {}).get("parseability", {}).get("details", {}).get("sections_detected", {})
        if not any(sections.values()):
            return None, "Skipped: No parseable sections detected"
    except Exception:
        pass
    
    # 1. INPUT GUARDRAILS
    if detect_prompt_injection(text):
        return None, "Skipped: Potential prompt injection detected"
        
    masked_text = mask_pii(text)
    
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
         return None, "Skipped: Missing API Key"
         
    system_prompt = (
        "You are a professional technical recruiter evaluating a resume against a specific role. "
        "Evaluate only skills, experience, and formatting relevant to that role. "
        "Do not comment on, infer, or score based on age, gender, ethnicity, nationality, or any other demographic characteristic. "
        "If the resume contains such information, ignore it entirely for scoring purposes.\n\n"
        "Return your evaluation strictly as JSON with exactly four keys: "
        "'field_relevance', 'structure', 'parseability', and 'impact'. Each key must map to an integer between 0 and 100."
    )
    
    user_prompt = f"Field: {field}\nHeuristic Reference Scores: {json.dumps(heuristic_result)}\n\nResume Text:\n{masked_text}"
    
    try:
        client = genai.Client(api_key=api_key)
        generation_config = types.GenerateContentConfig(
            temperature=0.0,
            response_mime_type="application/json",
            system_instruction=system_prompt,
        )
        response = client.models.generate_content(
            model=MODEL_NAME,
            contents=user_prompt,
            config=generation_config,
        )
        val = validate_llm_response(response.text)
        if val is not None:
             return val, "Success"
             
        # Retry logic: 3. OUTPUT VALIDATION GUARDRAILS
        retry_prompt = user_prompt + "\n\nCRITICAL: Your previous response was invalid. Return ONLY valid JSON with the 4 integer keys between 0 and 100."
        response_retry = client.models.generate_content(
            model=MODEL_NAME,
            contents=retry_prompt,
            config=generation_config,
        )
        val_retry = validate_llm_response(response_retry.text)
        if val_retry is not None:
             return val_retry, "Success"
        else:
             return None, "Failed: Invalid JSON output from LLM"
             
    except Exception as e:
        # Fallback for API errors (timeout, rate limit, auth, network)
        err_msg = str(e)
        if "timeout" in err_msg.lower():
             return None, "Failed: Timeout"
        elif "quota" in err_msg.lower() or "rate" in err_msg.lower() or "429" in err_msg:
             return None, "Failed: Rate limit exceeded"
        elif "api key" in err_msg.lower() or "auth" in err_msg.lower() or "401" in err_msg or "403" in err_msg:
             return None, "Failed: Authentication error"
        else:
             return None, f"Failed: API Error - {err_msg}"
