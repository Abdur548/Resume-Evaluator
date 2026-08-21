"""Error-contract regressions for the /evaluate endpoint.

Every case here previously returned HTTP 500 carrying the raw text of a
third-party exception ("File is not a zip file", "No /Root object! - Is this
really a PDF?"), which the frontend rendered directly to the user. These tests
pin both halves of the fix: malformed input is a 4xx, and nothing about the
server's internals reaches the client.
"""

import io
import zipfile

import pytest
from fastapi.testclient import TestClient

from backend import main
from backend.main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def clear_rate_limit():
    main.RATE_LIMIT.clear()
    yield
    main.RATE_LIMIT.clear()


def post_upload(filename, payload, field="backend_engineer"):
    return client.post(
        "/evaluate",
        data={"field": field},
        files={"file": (filename, payload, "application/octet-stream")},
    )


# (filename, payload, word expected in the caller-facing message)
CORRUPT_UPLOADS = [
    ("not-a-zip.docx", b"this is definitely not a docx", "docx"),
    ("truncated.docx", b"PK\x03\x04" + bytes(64), "docx"),
    ("not-a-pdf.pdf", b"hello world, not a pdf", "pdf"),
    ("empty.pdf", b"", "pdf"),
    ("header-only.pdf", b"%PDF-1.4\n", "pdf"),
]

# Substrings that betray the library, the filesystem, or the environment.
LEAKY_INTERNALS = [
    "File is not a zip file",
    "No /Root object",
    "Traceback",
    "AppData",
    "site-packages",
    "[Content_Types]",
    ".venv",
    "pdfminer",
    "zipfile",
]


@pytest.mark.parametrize("filename,payload,kind", CORRUPT_UPLOADS)
def test_corrupt_upload_is_client_error_not_server_error(filename, payload, kind):
    response = post_upload(filename, payload)

    assert response.status_code == 422, response.text
    error = response.json()["error"]
    assert error["code"] == "unreadable_document"
    assert kind in error["message"].lower()


@pytest.mark.parametrize("filename,payload,kind", CORRUPT_UPLOADS)
def test_corrupt_upload_leaks_no_internals(filename, payload, kind):
    text = post_upload(filename, payload).text

    for marker in LEAKY_INTERNALS:
        assert marker not in text, f"response leaked {marker!r}: {text}"


@pytest.mark.parametrize("filename,payload,kind", CORRUPT_UPLOADS)
def test_corrupt_upload_leaks_no_server_path(filename, payload, kind):
    """The upload is staged in a temp file whose path must never be echoed."""
    text = post_upload(filename, payload).text

    assert "Temp" not in text
    assert "tmp" not in text.lower().replace("attempt", "")


def test_valid_zip_that_is_not_an_office_package_is_rejected_cleanly():
    """python-docx raises a bare KeyError for this, which used to be a 500."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("hello.txt", "not an office document")

    response = post_upload("valid-zip.docx", buffer.getvalue())

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "unreadable_document"
    assert "[Content_Types]" not in response.text


def test_unexpected_failure_returns_generic_500(monkeypatch):
    """An unforeseen exception is logged server-side, not described to the caller."""

    def explode(path, field):
        raise RuntimeError("secret internal detail at C:/srv/app/config.yaml")

    monkeypatch.setattr(main.pipeline, "evaluate_resume", explode)

    # TestClient re-raises server exceptions by default, which would bypass the
    # handler under test. This asserts what a real HTTP client would receive.
    production_like = TestClient(app, raise_server_exceptions=False)
    response = production_like.post(
        "/evaluate",
        data={"field": "backend_engineer"},
        files={"file": ("resume.pdf", b"%PDF-1.4", "application/octet-stream")},
    )

    assert response.status_code == 500
    error = response.json()["error"]
    assert error["code"] == "internal_error"
    assert error["request_id"]
    assert "secret internal detail" not in response.text
    assert "config.yaml" not in response.text
    assert "RuntimeError" not in response.text


def test_missing_file_returns_one_readable_sentence():
    """FastAPI's raw validation array used to render as '[object Object]'."""
    response = client.post("/evaluate", data={"field": "backend_engineer"})

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "invalid_request"
    assert isinstance(error["message"], str)
    assert "file" in error["message"]


def test_all_error_responses_share_one_envelope():
    responses = [
        post_upload("resume.txt", b"text"),                       # 400
        post_upload("resume.pdf", b"%PDF-1.4", field="nonsense"),  # 400
        post_upload("broken.pdf", b"not a pdf"),                   # 422
        client.post("/evaluate", data={"field": "backend_engineer"}),  # 422
    ]

    for response in responses:
        body = response.json()
        assert set(body) == {"error"}, body
        assert set(body["error"]) == {"code", "message", "request_id"}
        assert isinstance(body["error"]["message"], str)


def test_request_id_is_unique_and_returned_in_the_header():
    first = client.get("/health")
    second = post_upload("resume.pdf", b"%PDF-1.4", field="nonsense")

    assert first.headers["X-Request-ID"]
    assert second.headers["X-Request-ID"]
    assert first.headers["X-Request-ID"] != second.headers["X-Request-ID"]
    assert second.headers["X-Request-ID"] == second.json()["error"]["request_id"]
