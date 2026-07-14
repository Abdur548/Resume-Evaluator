"""Match extracted JD requirements against normalized resume text."""

from .jd_parser import find_skill_mentions
from .requirement_extractor import extract_owned_qualifiers


def _evidence_snippet(text: str, start: int, end: int) -> str:
    line_start = text.rfind("\n", 0, start) + 1
    line_end = text.find("\n", end)
    if line_end == -1:
        line_end = len(text)
    return text[line_start:line_end].strip()


def match_requirement(requirement: dict, resume_text: str, field: str) -> dict:
    """Return the strongest explicit resume evidence for one requirement."""
    all_mentions = find_skill_mentions(resume_text, field)
    owned_qualifiers = extract_owned_qualifiers(resume_text, all_mentions)
    candidates = []

    for mention in all_mentions:
        if mention["skill_term"] != requirement["skill_term"]:
            continue
        key = (mention["start"], mention["end"], mention["skill_term"])
        qualifier = owned_qualifiers[key]
        candidates.append(
            {
                "claimed_years": qualifier["years"],
                "claimed_seniority": qualifier["seniority"],
                "matched_alias": mention["alias"],
                "evidence_snippet": _evidence_snippet(
                    resume_text, mention["start"], mention["end"]
                ),
                "_start": mention["start"],
            }
        )

    if not candidates:
        return {
            "presence": False,
            "claimed_years": None,
            "claimed_seniority": None,
            "matched_alias": None,
            "evidence_snippet": None,
        }

    candidates.sort(
        key=lambda item: (
            -(item["claimed_years"] is not None),
            -(item["claimed_seniority"] is not None),
            item["_start"],
        )
    )
    best = candidates[0]
    return {
        "presence": True,
        "claimed_years": best["claimed_years"],
        "claimed_seniority": best["claimed_seniority"],
        "matched_alias": best["matched_alias"],
        "evidence_snippet": best["evidence_snippet"],
    }


def match_requirements(requirements: list[dict], resume_text: str, field: str) -> list[dict]:
    return [
        {**requirement, **match_requirement(requirement, resume_text, field)}
        for requirement in requirements
    ]
