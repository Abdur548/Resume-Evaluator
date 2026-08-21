"""Match extracted JD requirements against normalized resume text."""

from .jd_parser import find_skill_mentions
from .requirement_extractor import extract_owned_qualifiers


def _evidence_snippet(text: str, start: int, end: int) -> str:
    line_start = text.rfind("\n", 0, start) + 1
    line_end = text.find("\n", end)
    if line_end == -1:
        line_end = len(text)
    return text[line_start:line_end].strip()


NO_EVIDENCE = {
    "presence": False,
    "claimed_years": None,
    "claimed_seniority": None,
    "matched_alias": None,
    "evidence_snippet": None,
}


def _index_evidence(resume_text: str, field: str) -> dict[str, list[dict]]:
    """Scan the resume once and group every mention by canonical skill.

    The scan does not depend on which requirement is being matched, so doing it
    per requirement meant re-reading the whole resume once per requirement --
    30 full scans for a 22-requirement job description.
    """
    mentions = find_skill_mentions(resume_text, field)
    owned_qualifiers = extract_owned_qualifiers(resume_text, mentions)

    by_skill: dict[str, list[dict]] = {}
    for mention in mentions:
        qualifier = owned_qualifiers[
            (mention["start"], mention["end"], mention["skill_term"])
        ]
        by_skill.setdefault(mention["skill_term"], []).append(
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

    # Strongest evidence first: an explicit years claim beats an explicit
    # seniority claim, and earlier placement breaks ties.
    for candidates in by_skill.values():
        candidates.sort(
            key=lambda item: (
                -(item["claimed_years"] is not None),
                -(item["claimed_seniority"] is not None),
                item["_start"],
            )
        )
    return by_skill


def _best_evidence(candidates: list[dict] | None) -> dict:
    if not candidates:
        return dict(NO_EVIDENCE)
    best = candidates[0]
    return {
        "presence": True,
        "claimed_years": best["claimed_years"],
        "claimed_seniority": best["claimed_seniority"],
        "matched_alias": best["matched_alias"],
        "evidence_snippet": best["evidence_snippet"],
    }


def match_requirement(requirement: dict, resume_text: str, field: str) -> dict:
    """Return the strongest explicit resume evidence for one requirement.

    Kept for single-requirement callers. Prefer match_requirements() for a set,
    which scans the resume once for all of them.
    """
    evidence = _index_evidence(resume_text, field)
    return _best_evidence(evidence.get(requirement["skill_term"]))


def match_requirements(requirements: list[dict], resume_text: str, field: str) -> list[dict]:
    evidence = _index_evidence(resume_text, field)
    return [
        {**requirement, **_best_evidence(evidence.get(requirement["skill_term"]))}
        for requirement in requirements
    ]
