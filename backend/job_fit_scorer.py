"""Deterministic job-description fit scoring."""

from .jd_parser import segment_requirements
from .requirement_extractor import SENIORITY_TIERS, extract_requirements
from .requirement_matcher import match_requirements


REQUIRED_WEIGHT = 0.80
PREFERRED_WEIGHT = 0.20
YEARS_RATIO_CAP = 1.20
MAX_SIGNAL_BONUS = 0.50

SENIORITY_BONUS_BY_DELTA = {
    -1: 0.35,
    -2: 0.20,
    -3: 0.10,
    -4: 0.05,
}


def _years_bonus(required_years: int, claimed_years: int) -> float:
    if required_years <= 0:
        return 0.0
    capped_ratio = min(claimed_years / required_years, YEARS_RATIO_CAP)
    return min(capped_ratio, 1.0) * MAX_SIGNAL_BONUS


def _seniority_bonus(required_seniority: str, claimed_seniority: str) -> float:
    required_index = SENIORITY_TIERS.index(required_seniority)
    claimed_index = SENIORITY_TIERS.index(claimed_seniority)
    delta = required_index - claimed_index
    if delta >= 0:
        return MAX_SIGNAL_BONUS
    return SENIORITY_BONUS_BY_DELTA.get(delta, 0.0)


def score_requirement(match: dict) -> dict:
    """Score one presence/evidence record in the closed range [0, 1]."""
    if not match["presence"]:
        return {**match, "match_score": 0.0}

    has_years_requirement = match["required_years"] is not None
    has_seniority_requirement = match["required_seniority"] is not None
    if not has_years_requirement and not has_seniority_requirement:
        return {**match, "match_score": 1.0}

    bonuses = []
    if match["required_years"] is not None and match["claimed_years"] is not None:
        bonuses.append(_years_bonus(match["required_years"], match["claimed_years"]))
    if (
        match["required_seniority"] is not None
        and match["claimed_seniority"] is not None
    ):
        bonuses.append(
            _seniority_bonus(
                match["required_seniority"], match["claimed_seniority"]
            )
        )

    bonus = sum(bonuses) / len(bonuses) if bonuses else 0.0
    return {**match, "match_score": round(min(0.5 + bonus, 1.0), 3)}


def _bucket_mean(scored: list[dict], bucket: str) -> float | None:
    values = [item["match_score"] for item in scored if item["bucket"] == bucket]
    return sum(values) / len(values) if values else None


def _aggregate_score(scored: list[dict]) -> int | None:
    required_mean = _bucket_mean(scored, "required")
    preferred_mean = _bucket_mean(scored, "preferred")

    if required_mean is None and preferred_mean is None:
        return None
    if preferred_mean is None:
        return round(required_mean * 100)
    if required_mean is None:
        return round(preferred_mean * 100)
    return round(
        (required_mean * REQUIRED_WEIGHT + preferred_mean * PREFERRED_WEIGHT) * 100
    )


def score_job_fit(resume_text: str, jd_text: str, field: str) -> dict:
    """Run the complete deterministic job-fit pipeline on extracted text."""
    units = segment_requirements(jd_text, field)
    requirements = extract_requirements(units, field)
    matched = match_requirements(requirements, resume_text, field)
    scored = [score_requirement(item) for item in matched]

    required = [item for item in scored if item["bucket"] == "required"]
    preferred = [item for item in scored if item["bucket"] == "preferred"]

    return {
        "job_fit_score": _aggregate_score(scored),
        "required": required,
        "preferred": preferred,
        "missing_required": list(
            dict.fromkeys(item["skill_term"] for item in required if not item["presence"])
        ),
        "missing_preferred": list(
            dict.fromkeys(item["skill_term"] for item in preferred if not item["presence"])
        ),
    }
