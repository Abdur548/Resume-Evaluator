"""
Regression / credibility tests for the heuristic scorer.

Run with: pytest test_scorer.py -v

These aren't happy-path tests. Each one exists because a specific failure
mode was found by adversarial testing. If any of these start failing after
a future change, that change reintroduced a known bug -- don't just update
the assertion, go read why the test exists first.
"""
import pytest
from pathlib import Path

from backend.scorer import score_resume

FIELD = "backend_engineer"
FIXTURES_DIR = Path(__file__).resolve().parent


def load(name):
    return (FIXTURES_DIR / name).read_text(encoding="utf-8")


def test_genuine_resume_beats_keyword_stuffing():
    """A real resume with real content must outscore a bare keyword dump
    by a wide margin. This is the core anti-gaming guarantee."""
    genuine = score_resume(load("sample_resume.txt"), FIELD)["total_score"]
    stuffed = score_resume(load("keyword_stuffed.txt"), FIELD)["total_score"]
    assert genuine > stuffed * 2, (
        f"Keyword stuffing scored too close to genuine content: "
        f"genuine={genuine}, stuffed={stuffed}"
    )


def test_keyword_stuffing_cannot_max_relevance():
    """A bare keyword list (zero bullets) must not get full relevance
    credit regardless of how many keywords it contains."""
    result = score_resume(load("keyword_stuffed.txt"), FIELD)
    relevance = result["categories"]["field_relevance"]["score"]
    max_relevance = result["categories"]["field_relevance"]["max"]
    assert relevance < max_relevance * 0.5, (
        f"Keyword stuffing got {relevance}/{max_relevance} relevance credit "
        "-- structural gate isn't working"
    )


def test_high_school_diploma_not_scored_as_college_degree():
    """A high-school-only candidate must not receive the same structure
    credit as a bachelor's/master's degree holder."""
    result = score_resume(load("weak_candidate.txt"), FIELD)
    structure = result["categories"]["structure"]["score"]
    assert structure < 20, (
        f"HS-diploma-only candidate scored {structure}/25 structure -- "
        "too close to a full degree credit"
    )


def test_genuine_resume_beats_off_field_weak_candidate():
    genuine = score_resume(load("sample_resume.txt"), FIELD)["total_score"]
    weak = score_resume(load("weak_candidate.txt"), FIELD)["total_score"]
    assert genuine > weak


def test_unstructured_wall_of_text_scores_low():
    """No bullets, no sections, no dates -- should score near the bottom
    regardless of what words appear in the prose."""
    result = score_resume(load("no_structure.txt"), FIELD)
    assert result["total_score"] < 20


def test_unknown_field_raises_not_silently_guesses():
    with pytest.raises(KeyError):
        score_resume(load("sample_resume.txt"), "underwater_basket_weaving")


def test_scoring_is_deterministic():
    """Same input must produce the exact same output every time --
    this is the entire point of the heuristic layer existing."""
    text = load("sample_resume.txt")
    r1 = score_resume(text, FIELD)
    r2 = score_resume(text, FIELD)
    assert r1 == r2


def test_gap_heavy_resume_penalized_but_not_zeroed():
    """Employment gaps should cost points without destroying the score
    entirely -- career-switchers and gap years are common and shouldn't
    be treated as disqualifying."""
    result = score_resume(load("gap_heavy.txt"), FIELD)
    structure = result["categories"]["structure"]["score"]
    assert 0 < structure < 20


def test_synonym_matching_catches_paraphrased_skills():
    """A resume using different wording than the corpus's literal terms
    must still get relevance credit -- this is the whole point of using
    synonym clusters instead of flat exact-match keyword lists."""
    result = score_resume(load("synonym_test.txt"), FIELD)
    matched = result["categories"]["field_relevance"]["details"]["skills_matched"]
    assert "load_balancing" in matched, (
        "Failed to match 'distributed traffic across servers' to load_balancing"
    )
    assert result["categories"]["field_relevance"]["score"] > 15


# --- Extraction layer tests ---
from backend.extract import extract_text


def test_pdf_and_docx_extraction_produce_identical_scores():
    """Same resume content, different file formats -- must score identically.
    This test exists because it originally didn't: a PDF bullet-glyph
    extraction artifact (cid codes) silently zeroed the impact score."""
    pdf_text = extract_text(str(FIXTURES_DIR / "sample_resume.pdf"))
    docx_text = extract_text(str(FIXTURES_DIR / "sample_resume.docx"))
    pdf_score = score_resume(pdf_text, FIELD)["total_score"]
    docx_score = score_resume(docx_text, FIELD)["total_score"]
    assert pdf_score == docx_score, (
        f"PDF ({pdf_score}) and DOCX ({docx_score}) extraction of identical "
        "content produced different scores -- bullet/text extraction is lossy"
    )


def test_pdf_extraction_recovers_bullets():
    text = extract_text(str(FIXTURES_DIR / "sample_resume.pdf"))
    bullet_lines = [l for l in text.split("\n") if l.strip().startswith("-")]
    assert len(bullet_lines) >= 3, (
        f"Expected >=3 bullets recovered from PDF, got {len(bullet_lines)}"
    )


def test_unsupported_file_type_raises():
    with pytest.raises(ValueError):
        extract_text("resume.txt")
