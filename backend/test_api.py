from fastapi.testclient import TestClient
from pathlib import Path
import pytest
from backend import main
from backend.main import app

client = TestClient(app)
FIXTURES_DIR = Path(__file__).resolve().parent


@pytest.fixture(autouse=True)
def clear_rate_limit():
    main.RATE_LIMIT.clear()
    yield
    main.RATE_LIMIT.clear()


def test_health_check():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_get_fields():
    response = client.get("/fields")
    assert response.status_code == 200
    assert "fields" in response.json()
    assert "backend_engineer" in response.json()["fields"]


def test_get_job_presets_returns_sourced_supported_profiles():
    response = client.get("/job-presets")

    assert response.status_code == 200
    presets = response.json()["presets"]
    assert {preset["id"] for preset in presets} == {
        "ai_ml_engineer",
        "computer_scientist",
        "software_engineer",
        "data_scientist",
        "cybersecurity_analyst",
    }
    assert len({preset["id"] for preset in presets}) == len(presets)
    for preset in presets:
        assert preset["field"] in main.VALID_FIELDS
        assert "Required Qualifications" in preset["description"]
        assert "Preferred Qualifications" in preset["description"]
        assert preset["sources"]
        assert all(source["url"].startswith("https://") for source in preset["sources"])


def test_evaluate_valid_pdf():
    field = "backend_engineer"
    with (FIXTURES_DIR / "sample_resume.pdf").open("rb") as f:
        response = client.post(
            "/evaluate",
            data={"field": field},
            files={"file": ("sample_resume.pdf", f, "application/pdf")}
        )
    assert response.status_code == 200
    data = response.json()
    assert "heuristic_evaluation" in data
    assert "llm_evaluation" in data
    assert "llm_evaluation_status" in data
    assert "job_fit_evaluation" not in data


def test_evaluate_valid_docx():
    field = "backend_engineer"
    with (FIXTURES_DIR / "sample_resume.docx").open("rb") as f:
        response = client.post(
            "/evaluate",
            data={"field": field},
            files={"file": ("sample_resume.docx", f, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")}
        )
    assert response.status_code == 200
    data = response.json()
    assert "heuristic_evaluation" in data
    assert "llm_evaluation" in data
    assert "llm_evaluation_status" in data
    assert "job_fit_evaluation" not in data


def test_evaluate_invalid_file_type():
    response = client.post(
        "/evaluate",
        data={"field": "backend_engineer"},
        files={"file": ("sample_resume.txt", b"This is a test resume.", "text/plain")}
    )
    assert response.status_code == 400
    assert "Only .pdf and .docx are supported" in response.json()["detail"]


def test_evaluate_invalid_field():
    with (FIXTURES_DIR / "sample_resume.pdf").open("rb") as f:
        response = client.post(
            "/evaluate",
            data={"field": "unknown_field"},
            files={"file": ("sample_resume.pdf", f, "application/pdf")}
        )
    assert response.status_code == 400
    assert "Invalid field" in response.json()["detail"]


def test_evaluate_no_file():
    response = client.post(
        "/evaluate",
        data={"field": "backend_engineer"}
    )
    assert response.status_code == 422  # FastAPI built-in validation error for missing file


def test_evaluate_rejects_oversized_upload():
    oversized = b"x" * (main.MAX_FILE_SIZE + 1)
    response = client.post(
        "/evaluate",
        data={"field": "backend_engineer"},
        files={"file": ("oversized.pdf", oversized, "application/pdf")}
    )
    assert response.status_code == 413
    assert "File too large" in response.json()["detail"]


def test_evaluate_rate_limits_by_client_ip(monkeypatch):
    monkeypatch.setattr(
        main.pipeline,
        "evaluate_resume",
        lambda path, field: {
            "heuristic_evaluation": {"total_score": 75},
            "llm_evaluation": None,
            "llm_evaluation_status": "Skipped: Missing API Key",
        },
    )

    for _ in range(main.RATE_LIMIT_MAX):
        response = client.post(
            "/evaluate",
            data={"field": "backend_engineer"},
            files={"file": ("sample_resume.pdf", b"%PDF-1.4", "application/pdf")}
        )
        assert response.status_code == 200

    blocked = client.post(
        "/evaluate",
        data={"field": "backend_engineer"},
        files={"file": ("sample_resume.pdf", b"%PDF-1.4", "application/pdf")}
    )
    assert blocked.status_code == 429
    assert "Too many requests" in blocked.json()["detail"]

def test_evaluate_with_jd_adds_job_fit_keys(monkeypatch):
    monkeypatch.setattr(
        main.pipeline,
        "evaluate_resume",
        lambda path, field: {
            "heuristic_evaluation": {"total_score": 75},
            "llm_evaluation": None,
            "llm_evaluation_status": "Skipped: Missing API Key",
        },
    )
    monkeypatch.setattr(
        main.pipeline,
        "evaluate_job_fit",
        lambda path, field, jd_text: {
            "job_fit_evaluation": {"job_fit_score": 50},
            "llm_job_fit_evaluation": None,
            "llm_job_fit_evaluation_status": "Skipped: Missing API Key",
        },
    )

    response = client.post(
        "/evaluate",
        data={"field": "backend_engineer", "jd_text": "Required\n- Python"},
        files={"file": ("sample_resume.pdf", b"%PDF-1.4", "application/pdf")},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["heuristic_evaluation"]["total_score"] == 75
    assert data["job_fit_evaluation"]["job_fit_score"] == 50
    assert "llm_job_fit_evaluation" in data
    assert "llm_job_fit_evaluation_status" in data
