"""Extract deterministic skill requirements from parsed JD units."""

import re

from .jd_parser import find_skill_mentions


# Ordered from highest to lowest. This v1 list is intentionally finite and
# should be expanded only with test-backed scoring decisions.
SENIORITY_TIERS = (
    "expert",
    "advanced",
    "senior",
    "proficient",
    "intermediate",
    "familiar",
    "basic",
    "entry",
    "junior",
)

YEARS_PATTERN = re.compile(r"\b(\d{1,2})\s*\+?\s*(?:years?|yrs?)\b", re.IGNORECASE)
SENIORITY_PATTERN = re.compile(
    r"\b(" + "|".join(re.escape(tier) for tier in SENIORITY_TIERS) + r")\b",
    re.IGNORECASE,
)
CLAUSE_BOUNDARY_PATTERN = re.compile(r"[;\n.!?]")
TOKEN_PATTERN = re.compile(r"\S+")
QUALIFIER_TOKEN_WINDOW = 15


def _clause_bounds(text: str, start: int, end: int) -> tuple[int, int]:
    left = 0
    right = len(text)
    for boundary in CLAUSE_BOUNDARY_PATTERN.finditer(text):
        if boundary.end() <= start:
            left = boundary.end()
        elif boundary.start() >= end:
            right = boundary.start()
            break
    return left, right


def _token_distance(text: str, first: tuple[int, int], second: tuple[int, int]) -> int:
    gap_start = min(first[1], second[1])
    gap_end = max(first[0], second[0])
    if gap_end <= gap_start:
        return 0
    return len(TOKEN_PATTERN.findall(text[gap_start:gap_end]))


def _qualifier_owner(
    text: str,
    qualifier_span: tuple[int, int],
    skill_mentions: list[dict],
    token_window: int,
) -> dict | None:
    q_start, q_end = qualifier_span
    clause_start, clause_end = _clause_bounds(text, q_start, q_end)
    candidates = []

    for mention in skill_mentions:
        if mention["start"] < clause_start or mention["end"] > clause_end:
            continue
        distance = _token_distance(
            text,
            qualifier_span,
            (mention["start"], mention["end"]),
        )
        if distance <= token_window:
            candidates.append((distance, mention["start"], mention))

    if not candidates:
        return None
    candidates.sort(key=lambda item: (item[0], item[1]))
    if len(candidates) > 1 and candidates[0][0] == candidates[1][0]:
        return None
    return candidates[0][2]


def extract_owned_qualifiers(
    text: str,
    skill_mentions: list[dict],
    token_window: int = QUALIFIER_TOKEN_WINDOW,
) -> dict[tuple[int, int, str], dict]:
    """Assign each nearby qualifier to at most one explicit skill mention."""
    owned = {
        (mention["start"], mention["end"], mention["skill_term"]): {
            "years": None,
            "seniority": None,
        }
        for mention in skill_mentions
    }

    for match in YEARS_PATTERN.finditer(text):
        owner = _qualifier_owner(text, match.span(), skill_mentions, token_window)
        if owner:
            key = (owner["start"], owner["end"], owner["skill_term"])
            if owned[key]["years"] is None:
                owned[key]["years"] = int(match.group(1))

    for match in SENIORITY_PATTERN.finditer(text):
        owner = _qualifier_owner(text, match.span(), skill_mentions, token_window)
        if owner:
            key = (owner["start"], owner["end"], owner["skill_term"])
            if owned[key]["seniority"] is None:
                owned[key]["seniority"] = match.group(1).lower()

    return owned


def extract_requirements(units: list[dict], field: str) -> list[dict]:
    """Expand requirement units into one record per canonical skill."""
    requirements_by_skill = {}
    for unit in units:
        text = unit["raw_text"]
        mentions = find_skill_mentions(text, field)
        qualifiers = extract_owned_qualifiers(text, mentions)
        seen_skills = set()

        for mention in mentions:
            skill = mention["skill_term"]
            if skill in seen_skills:
                continue
            seen_skills.add(skill)
            key = (mention["start"], mention["end"], skill)
            requirement = qualifiers[key]
            candidate = {
                "skill_term": skill,
                "required_years": requirement["years"],
                "required_seniority": requirement["seniority"],
                "bucket": unit["bucket"],
                "raw_text": text,
            }
            existing = requirements_by_skill.get(skill)
            if existing is None:
                requirements_by_skill[skill] = candidate
                continue

            # A canonical capability should affect the score only once. When a
            # JD repeats it, retain the stricter explicit qualifier and keep a
            # required occurrence ahead of a preferred one.
            if candidate["bucket"] == "required" and existing["bucket"] != "required":
                existing["bucket"] = "required"
                existing["raw_text"] = candidate["raw_text"]
            if candidate["required_years"] is not None:
                existing["required_years"] = max(
                    existing["required_years"] or 0,
                    candidate["required_years"],
                )
            candidate_seniority = candidate["required_seniority"]
            existing_seniority = existing["required_seniority"]
            if candidate_seniority and (
                existing_seniority is None
                or SENIORITY_TIERS.index(candidate_seniority)
                < SENIORITY_TIERS.index(existing_seniority)
            ):
                existing["required_seniority"] = candidate_seniority

    return list(requirements_by_skill.values())
