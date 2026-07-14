from . import extract, job_fit_llm, job_fit_scorer, llm, scorer

def evaluate_resume(filepath: str, field: str) -> dict:
    """Extracts text from a resume and scores it using the deterministic heuristic engine, optionally adding an LLM evaluation."""
    text = extract.extract_text(filepath)
    heuristic_result = scorer.score_resume(text, field)
    
    llm_eval, llm_status = llm.get_llm_evaluation(text, field, heuristic_result)
    
    return {
        "heuristic_evaluation": heuristic_result,
        "llm_evaluation": llm_eval,
        "llm_evaluation_status": llm_status
    }


def evaluate_job_fit(resume_filepath: str, field: str, jd_text: str) -> dict:
    """Evaluate an extracted resume against an optional job description."""
    text = extract.extract_text(resume_filepath)
    heuristic_result = job_fit_scorer.score_job_fit(text, jd_text, field)
    llm_eval, llm_status = job_fit_llm.get_llm_job_fit_evaluation(
        text, jd_text, heuristic_result
    )

    return {
        "job_fit_evaluation": heuristic_result,
        "llm_job_fit_evaluation": llm_eval,
        "llm_job_fit_evaluation_status": llm_status,
    }
