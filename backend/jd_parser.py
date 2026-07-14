"""Deterministic job-description section and requirement parsing."""

import re

from .scorer import load_field_corpus


REQUIRED_HEADER_PATTERNS = (
    r"required(?: qualifications?| skills?)?",
    r"requirements?",
    r"must[- ]have(?: qualifications?| skills?)?",
    r"minimum qualifications?",
    r"you have",
    r"what you(?:'|\u2019)?ll need",
    r"what you will need",
)

PREFERRED_HEADER_PATTERNS = (
    r"preferred(?: qualifications?| skills?)?",
    r"nice[- ]to[- ]have(?: qualifications?| skills?)?",
    r"bonus(?: qualifications?| skills?)?",
    r"a plus",
    r"desirable",
)

BULLET_PATTERN = re.compile(r"^\s*[-*\u2022]\s+")
SENTENCE_PATTERN = re.compile(r"(?<=[.!?])\s+")


def _header_bucket(line: str) -> str | None:
    candidate = line.strip().strip("#: ").lower()
    if not candidate or len(candidate) > 80:
        return None
    if any(re.fullmatch(pattern, candidate, re.IGNORECASE) for pattern in PREFERRED_HEADER_PATTERNS):
        return "preferred"
    if any(re.fullmatch(pattern, candidate, re.IGNORECASE) for pattern in REQUIRED_HEADER_PATTERNS):
        return "required"
    return None


def split_jd_sections(jd_text: str) -> dict:
    """Split JD lines into required/preferred buckets.

    Content before the first recognized header is required. Headerless JDs
    therefore naturally fall back to 100% required content.
    """
    buckets = {"required": [], "preferred": []}
    current_bucket = "required"
    headers_detected = False

    for raw_line in (jd_text or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        header_bucket = _header_bucket(line)
        if header_bucket:
            current_bucket = header_bucket
            headers_detected = True
            continue
        buckets[current_bucket].append(line)

    return {
        "required": buckets["required"],
        "preferred": buckets["preferred"],
        "headers_detected": headers_detected,
    }


def _alias_pattern(alias: str) -> re.Pattern:
    escaped = re.escape(alias.strip())
    escaped = escaped.replace(r"\ ", r"\s+")
    return re.compile(
        rf"(?<![A-Za-z0-9+#]){escaped}(?![A-Za-z0-9+#])",
        re.IGNORECASE,
    )


def skill_aliases(field: str) -> dict[str, list[str]]:
    """Return canonical skills and their searchable aliases."""
    corpus = load_field_corpus(field)
    aliases = {}
    for canonical, synonyms in corpus.items():
        values = [canonical.replace("_", " "), *synonyms]
        aliases[canonical] = sorted(set(values), key=lambda value: (-len(value), value))
    return aliases


def find_skill_mentions(text: str, field: str) -> list[dict]:
    """Locate exact alias spans and return canonical skill ownership."""
    mentions = []
    for canonical, aliases in skill_aliases(field).items():
        for alias in aliases:
            for match in _alias_pattern(alias).finditer(text):
                mentions.append(
                    {
                        "skill_term": canonical,
                        "alias": match.group(0),
                        "start": match.start(),
                        "end": match.end(),
                    }
                )

    # Prefer longer aliases when aliases in the same canonical cluster overlap.
    mentions.sort(key=lambda item: (item["start"], -(item["end"] - item["start"]), item["skill_term"]))
    deduplicated = []
    for mention in mentions:
        if any(
            existing["skill_term"] == mention["skill_term"]
            and mention["start"] < existing["end"]
            and mention["end"] > existing["start"]
            for existing in deduplicated
        ):
            continue
        deduplicated.append(mention)
    return sorted(deduplicated, key=lambda item: (item["start"], item["end"]))


def _contains_skill(text: str, field: str) -> bool:
    return bool(find_skill_mentions(text, field))


def segment_requirements(jd_text: str, field: str) -> list[dict]:
    """Split section buckets into deterministic requirement units."""
    sections = split_jd_sections(jd_text)
    units = []

    for bucket in ("required", "preferred"):
        lines = sections[bucket]
        has_bullets = any(BULLET_PATTERN.match(line) for line in lines)

        for line in lines:
            cleaned = BULLET_PATTERN.sub("", line).strip()
            if not cleaned:
                continue

            dense_sentences = SENTENCE_PATTERN.split(cleaned)
            if not has_bullets and len(lines) == 1 and len(dense_sentences) > 1:
                candidates = [sentence.strip() for sentence in dense_sentences]
                candidates = [sentence for sentence in candidates if _contains_skill(sentence, field)]
            else:
                candidates = [cleaned]

            units.extend(
                {"raw_text": candidate, "bucket": bucket}
                for candidate in candidates
                if candidate
            )

    return units
