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


def assert_error(response, expected_code, expected_text):
    """Every error response uses one envelope: error.code / message / request_id."""
    body = response.json()
    assert set(body) == {"error"}, body
    error = body["error"]
    assert set(error) == {"code", "message", "request_id"}, error
    assert error["code"] == expected_code
    assert expected_text in error["message"]
    assert error["request_id"]
    assert response.headers["X-Request-ID"] == error["request_id"]


def test_health_check():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_cors_origins_default_to_local_frontends():
    assert main.parse_cors_origins(None) == list(main.DEFAULT_CORS_ORIGINS)
    assert main.parse_cors_origins("   ") == list(main.DEFAULT_CORS_ORIGINS)


def test_cors_origins_are_normalized_and_deduplicated():
    assert main.parse_cors_origins(
        "HTTPS://RESUME.EXAMPLE.COM/, http://localhost:5173, "
        "https://resume.example.com"
    ) == ["https://resume.example.com", "http://localhost:5173"]


@pytest.mark.parametrize(
    "origins",
    [
        "*",
        "resume.example.com",
        "ftp://resume.example.com",
        "https://resume.example.com/app",
        "https://resume.example.com?preview=1",
        "https://user:password@resume.example.com",
    ],
)
def test_cors_origins_reject_invalid_values(origins):
    with pytest.raises(RuntimeError, match="CORS_ORIGINS"):
        main.parse_cors_origins(origins)


def test_cors_preflight_allows_default_frontend():
    response = client.options(
        "/evaluate",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"


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
    assert_error(response, "invalid_file_type", "Only .pdf and .docx are supported")


def test_evaluate_invalid_field():
    with (FIXTURES_DIR / "sample_resume.pdf").open("rb") as f:
        response = client.post(
            "/evaluate",
            data={"field": "unknown_field"},
            files={"file": ("sample_resume.pdf", f, "application/pdf")}
        )
    assert response.status_code == 400
    assert_error(response, "invalid_field", "Invalid field")


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
    assert_error(response, "file_too_large", "File too large")


def test_evaluate_rejects_oversized_job_description():
    response = client.post(
        "/evaluate",
        data={
            "field": "backend_engineer",
            "jd_text": "x" * (main.MAX_JOB_DESCRIPTION_LENGTH + 1),
        },
        files={"file": ("sample_resume.pdf", b"%PDF-1.4", "application/pdf")},
    )
    assert response.status_code == 413
    assert_error(response, "job_description_too_large", "Job description too large")


def test_evaluate_rate_limits_by_client_ip(monkeypatch):
    monkeypatch.setattr(
        main.pipeline,
        "evaluate_upload",
        lambda path, field, jd_text=None: {
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
    assert_error(blocked, "rate_limited", "Too many requests")

def test_evaluate_with_jd_adds_job_fit_keys(monkeypatch):
    def fake_upload(path, field, jd_text=None):
        result = {
            "heuristic_evaluation": {"total_score": 75},
            "llm_evaluation": None,
            "llm_evaluation_status": "Skipped: Missing API Key",
        }
        if jd_text and jd_text.strip():
            result.update(
                {
                    "job_fit_evaluation": {"job_fit_score": 50},
                    "llm_job_fit_evaluation": None,
                    "llm_job_fit_evaluation_status": "Skipped: Missing API Key",
                }
            )
        return result

    monkeypatch.setattr(main.pipeline, "evaluate_upload", fake_upload)

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
