from pathlib import Path

from backend import pipeline


FIXTURES_DIR = Path(__file__).resolve().parent

def test_evaluate_resume_same_score():
    field = "backend_engineer"
    result_pdf = pipeline.evaluate_resume(str(FIXTURES_DIR / "sample_resume.pdf"), field)
    result_docx = pipeline.evaluate_resume(str(FIXTURES_DIR / "sample_resume.docx"), field)
    
    assert result_pdf['heuristic_evaluation']['total_score'] == result_docx['heuristic_evaluation']['total_score']


def test_evaluate_job_fit_is_additive(monkeypatch):
    monkeypatch.setattr(
        pipeline.extract,
        "extract_text",
        lambda path: "EXPERIENCE\n- 5 years Python",
    )
    monkeypatch.setattr(
        pipeline.job_fit_llm,
        "get_llm_job_fit_evaluation",
        lambda resume, jd, heuristic: (None, "Skipped: Missing API Key"),
    )

    result = pipeline.evaluate_job_fit(
        "resume.pdf",
        "backend_engineer",
        "Required\n- 3 years Python",
    )

    assert result["job_fit_evaluation"]["job_fit_score"] == 100
    assert result["llm_job_fit_evaluation"] is None
    assert "heuristic_evaluation" not in result
