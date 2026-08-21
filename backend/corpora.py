"""Shared access to the per-field skill corpus.

This lives in its own module for two reasons.

Layering: `jd_parser` previously imported `load_field_corpus` from `scorer`,
so the parsing layer depended on the scoring layer purely to read a data file.

Cost: the loader re-read and re-parsed field_corpora.json on every call, and
the matcher called it once per requirement -- 30 disk reads and 30 JSON parses
for a single evaluation. The corpus is read-only application data, so it is
cached for the process lifetime.
"""

import json
from functools import lru_cache
from pathlib import Path

CORPORA_PATH = Path(__file__).parent / "field_corpora.json"


@lru_cache(maxsize=1)
def load_corpora() -> dict:
    """Return the full corpus file, parsed once per process."""
    if not CORPORA_PATH.exists():
        raise FileNotFoundError(f"No corpora file at {CORPORA_PATH}")
    return json.loads(CORPORA_PATH.read_text(encoding="utf-8"))


def available_fields() -> list[str]:
    return list(load_corpora().keys())


def load_field_corpus(field: str) -> dict:
    """Return ``{canonical_skill: [synonym, ...]}`` for one field."""
    data = load_corpora()
    if field not in data:
        raise KeyError(
            f"Unknown field '{field}'. Available: {list(data.keys())}. "
            "Add it to field_corpora.json first."
        )
    return data[field]


def reset_cache() -> None:
    """Drop this module's cached corpus data.

    Not sufficient on its own for a test that edits field_corpora.json:
    `jd_parser` caches alias lists derived from this data and will keep serving
    them. Call `jd_parser.reset_caches()` as well -- or `reset_all_caches()`,
    which does both.
    """
    load_corpora.cache_clear()


def reset_all_caches() -> None:
    """Drop every cache derived from the corpus file.

    Imported locally to keep this module free of a dependency on its consumers.
    """
    from . import jd_parser

    load_corpora.cache_clear()
    jd_parser.reset_caches()
