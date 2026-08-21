from . import extract, job_fit_llm, job_fit_scorer, llm, scorer


def evaluate_resume_text(text: str, field: str) -> dict:
    """Score already-extracted resume text with the deterministic engine,
    optionally adding an LLM evaluation."""
    heuristic_result = scorer.score_resume(text, field)

    llm_eval, llm_status = llm.get_llm_evaluation(text, field, heuristic_result)

    return {
        "heuristic_evaluation": heuristic_result,
        "llm_evaluation": llm_eval,
        "llm_evaluation_status": llm_status,
    }


def evaluate_job_fit_text(text: str, field: str, jd_text: str) -> dict:
    """Evaluate already-extracted resume text against a job description."""
    heuristic_result = job_fit_scorer.score_job_fit(text, jd_text, field)
    llm_eval, llm_status = job_fit_llm.get_llm_job_fit_evaluation(
        text, jd_text, heuristic_result
    )

    return {
        "job_fit_evaluation": heuristic_result,
        "llm_job_fit_evaluation": llm_eval,
        "llm_job_fit_evaluation_status": llm_status,
    }


def evaluate_upload(filepath: str, field: str, jd_text: str | None = None) -> dict:
    """Run every requested evaluation over one upload, extracting it once.

    The resume and job-fit paths each used to open and parse the file
    themselves, so a request carrying a job description parsed the same PDF
    twice and discarded the first result.
    """
    text = extract.extract_text(filepath)
    result = evaluate_resume_text(text, field)
    if jd_text and jd_text.strip():
        result.update(evaluate_job_fit_text(text, field, jd_text))
    return result


def evaluate_resume(filepath: str, field: str) -> dict:
    """Extracts text from a resume and scores it using the deterministic heuristic engine, optionally adding an LLM evaluation."""
    return evaluate_resume_text(extract.extract_text(filepath), field)


def evaluate_job_fit(filepath: str, field: str, jd_text: str) -> dict:
    """Evaluate an extracted resume against an optional job description."""
    return evaluate_job_fit_text(extract.extract_text(filepath), field, jd_text)
