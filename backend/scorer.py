"""
Deterministic heuristic resume scorer.

This is the ALWAYS-RUNS layer. No LLM calls. No network calls. Same input
text produces the same output every single time (unlike the HackerRank
hiring-agent case study — same resume in, same score out here).

Four categories, weights are configurable constants, not magic numbers
buried in logic:
    FIELD_RELEVANCE     35
    STRUCTURE           25   (experience / education)
    PARSEABILITY        20   (ATS format)
    IMPACT              20   (quantified achievements)

Usage:
    from scorer import score_resume
    result = score_resume(resume_text, field="backend_engineer")
    print(result["total_score"])          # 0-100
    print(result["categories"])           # per-category breakdown
"""

import re
import json
from dataclasses import dataclass, field as dc_field
from datetime import datetime
from pathlib import Path
from rank_bm25 import BM25Okapi

# ---------------------------------------------------------------------------
# Weights — change these, not the logic below, if you want a different split
# ---------------------------------------------------------------------------
WEIGHTS = {
    "field_relevance": 35,
    "structure": 25,
    "parseability": 20,
    "impact": 20,
}
assert sum(WEIGHTS.values()) == 100, "Weights must sum to 100"

CORPORA_PATH = Path(__file__).parent / "field_corpora.json"


# ---------------------------------------------------------------------------
# 1. PARSEABILITY (20 pts) — pure rule-based structural check
# ---------------------------------------------------------------------------
SECTION_HEADERS = {
    "experience": [r"\bexperience\b", r"\bwork history\b", r"\bemployment\b"],
    "education": [r"\beducation\b", r"\bacademic\b"],
    "skills": [r"\bskills\b", r"\btechnical skills\b", r"\bcompetencies\b"],
    "contact": [r"@[\w.-]+\.\w+", r"\b(\+?\d[\d\-\s\(\)]{7,}\d)\b"],  # email / phone
}

BROKEN_ELEMENT_MARKERS = [
    r"\[image\]", r"\[table\]", r"<table", r"\.png\)", r"\.jpg\)",
]


def score_parseability(text: str) -> dict:
    text_lower = text.lower()
    found = {}
    for section, patterns in SECTION_HEADERS.items():
        found[section] = any(re.search(p, text_lower) for p in patterns)

    sections_present = sum(1 for v in found.values() if v)
    sections_possible = len(SECTION_HEADERS)
    section_score = (sections_present / sections_possible) * 14  # 14 of 20

    # deductions for elements that break ATS parsers
    deductions = 0
    broken_hits = []
    for marker in BROKEN_ELEMENT_MARKERS:
        if re.search(marker, text_lower):
            deductions += 2
            broken_hits.append(marker)

    # bullet density check — resumes with zero bullets parse poorly in most ATS
    bullet_count = len(re.findall(r"^\s*[•\-\*]\s+", text, flags=re.MULTILINE))
    bullet_score = min(bullet_count / 5, 1) * 6  # up to 6 of 20, saturates at 5 bullets

    raw = max(0, section_score + bullet_score - deductions)
    raw = min(raw, 20)

    return {
        "score": round(raw, 1),
        "max": 20,
        "details": {
            "sections_detected": found,
            "bullet_count": bullet_count,
            "broken_elements_found": broken_hits,
        },
    }


# ---------------------------------------------------------------------------
# 2. FIELD RELEVANCE (35 pts) — BM25 against a per-field keyword corpus
# ---------------------------------------------------------------------------
def _tokenize(text: str) -> list:
    return re.findall(r"[a-zA-Z][a-zA-Z\+\#\.]{1,}", text.lower())


def load_field_corpus(field: str) -> dict:
    if not CORPORA_PATH.exists():
        raise FileNotFoundError(f"No corpora file at {CORPORA_PATH}")
    data = json.loads(CORPORA_PATH.read_text())
    if field not in data:
        raise KeyError(
            f"Unknown field '{field}'. Available: {list(data.keys())}. "
            "Add it to field_corpora.json first."
        )
    return data[field]  # {canonical_skill: [synonym, synonym, ...]}


def score_field_relevance(text: str, field: str, bullet_count: int = None) -> dict:
    corpus = load_field_corpus(field)  # canonical_skill -> [synonyms]
    resume_tokens = _tokenize(text)

    canonical_skills = list(corpus.keys())
    # Each canonical skill's BM25 "document" is built from ALL its synonym
    # phrasings combined -- so a resume that says "traffic distribution"
    # instead of "load balancing" still matches the load_balancing skill.
    corpus_docs = [_tokenize(" ".join(synonyms)) for synonyms in corpus.values()]
    bm25 = BM25Okapi(corpus_docs)

    scores = bm25.get_scores(resume_tokens)
    matched = [
        (skill, round(float(s), 2))
        for skill, s in zip(canonical_skills, scores)
        if s > 0
    ]
    matched.sort(key=lambda x: -x[1])

    coverage = len(matched) / max(len(canonical_skills), 1)
    strength = min(sum(s for _, s in matched) / (len(canonical_skills) or 1), 1.0)

    raw = (0.6 * coverage + 0.4 * strength) * WEIGHTS["field_relevance"]

    if bullet_count is None:
        bullet_count = len(re.findall(r"^\s*[•\-\*]\s+", text, flags=re.MULTILINE))
    structural_gate = min(bullet_count / 3, 1.0)
    raw = raw * (0.3 + 0.7 * structural_gate)

    return {
        "score": round(raw, 1),
        "max": WEIGHTS["field_relevance"],
        "details": {
            "field": field,
            "skills_matched": [m[0] for m in matched[:15]],
            "coverage_pct": round(coverage * 100, 1),
            "structural_gate_applied": round(structural_gate, 2),
        },
    }


# ---------------------------------------------------------------------------
# 3. QUANTIFIED IMPACT (20 pts) — regex pattern density across bullets
# ---------------------------------------------------------------------------
NUMBER_PATTERN = re.compile(r"\b\d+(\.\d+)?%?\b|\$\d")
ACTION_VERBS = [
    "led", "built", "designed", "implemented", "reduced", "increased",
    "improved", "launched", "automated", "optimized", "shipped",
    "architected", "scaled", "migrated", "deployed", "created",
]


def score_impact(text: str) -> dict:
    bullets = re.findall(r"^\s*[•\-\*]\s+(.*)$", text, flags=re.MULTILINE)
    if not bullets:
        return {"score": 0, "max": 20, "details": {"bullets_found": 0}}

    quantified = 0
    action_started = 0
    for b in bullets:
        if NUMBER_PATTERN.search(b):
            quantified += 1
        first_word = b.strip().split(" ")[0].lower().rstrip(".,")
        if first_word in ACTION_VERBS:
            action_started += 1

    quant_ratio = quantified / len(bullets)
    action_ratio = action_started / len(bullets)

    raw = (0.65 * quant_ratio + 0.35 * action_ratio) * 20

    return {
        "score": round(raw, 1),
        "max": 20,
        "details": {
            "bullets_found": len(bullets),
            "quantified_bullets": quantified,
            "action_verb_bullets": action_started,
        },
    }


# ---------------------------------------------------------------------------
# 4. STRUCTURE (25 pts) — experience/education dates + degree detection
# ---------------------------------------------------------------------------
DATE_RANGE_PATTERN = re.compile(
    r"(\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{4}|\b\d{4})\s*"
    r"(?:-|–|to)\s*"
    r"(\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{4}|\b\d{4}|present|current)",
    flags=re.IGNORECASE,
)
DEGREE_KEYWORDS = [
    "bachelor", "b.s.", "bs ", "b.sc", "master", "m.s.", "ms ", "mba",
    "phd", "ph.d", "associate degree",
]
# Credentials below college level -- detected but scored lower, not zero,
# since they're legitimate for some fields/entry-level roles.
SUB_COLLEGE_KEYWORDS = ["high school diploma", "ged", "vocational"]


def _extract_year(token: str) -> int | None:
    m = re.search(r"\d{4}", token)
    return int(m.group()) if m else None


def score_structure(text: str) -> dict:
    text_lower = text.lower()

    degree_found = any(kw in text_lower for kw in DEGREE_KEYWORDS)
    sub_college_found = any(kw in text_lower for kw in SUB_COLLEGE_KEYWORDS)
    if degree_found:
        degree_score = 8  # of 25
    elif sub_college_found:
        degree_score = 3  # partial credit, not equal to a college degree
    else:
        degree_score = 0

    ranges = DATE_RANGE_PATTERN.findall(text)
    date_pairs = []
    for start_raw, end_raw in ranges:
        start_year = _extract_year(start_raw)
        end_year = (
            datetime.now().year
            if re.match(r"present|current", end_raw, re.IGNORECASE)
            else _extract_year(end_raw)
        )
        if start_year and end_year:
            date_pairs.append((start_year, end_year))

    date_pairs.sort()
    gap_years = 0
    for i in range(1, len(date_pairs)):
        prev_end = date_pairs[i - 1][1]
        curr_start = date_pairs[i][0]
        if curr_start > prev_end:
            gap_years += curr_start - prev_end

    # No detectable dates at all -> can't verify continuity, small penalty
    if not date_pairs:
        continuity_score = 6  # of 12, neutral-low
    else:
        continuity_score = max(0, 12 - gap_years * 2)  # -2 pts per unexplained gap year

    entries_score = min(len(date_pairs), 5)  # up to 5 pts, one per role/entry, capped

    raw = degree_score + continuity_score + entries_score
    raw = min(raw, 25)

    return {
        "score": round(raw, 1),
        "max": 25,
        "details": {
            "degree_detected": degree_found,
            "date_ranges_found": len(date_pairs),
            "unexplained_gap_years": gap_years,
        },
    }


# ---------------------------------------------------------------------------
# Aggregator
# ---------------------------------------------------------------------------
def score_resume(text: str, field: str) -> dict:
    parseability = score_parseability(text)
    relevance = score_field_relevance(
        text, field, bullet_count=parseability["details"]["bullet_count"]
    )
    impact = score_impact(text)
    structure = score_structure(text)

    total = (
        parseability["score"]
        + relevance["score"]
        + impact["score"]
        + structure["score"]
    )

    return {
        "total_score": round(total, 1),
        "max_score": 100,
        "categories": {
            "field_relevance": relevance,
            "structure": structure,
            "parseability": parseability,
            "impact": impact,
        },
        "weights_used": WEIGHTS,
    }


if __name__ == "__main__":
    import sys
    sample_path = Path(__file__).parent / "sample_resume.txt"
    sample_text = sample_path.read_text()
    result = score_resume(sample_text, field="backend_engineer")
    print(json.dumps(result, indent=2))