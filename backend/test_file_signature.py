"""Upload content verification (SEC-08).

The endpoint previously trusted the filename suffix, so a renamed or corrupt
file reached a third-party parser before anything checked it. These tests pin
the content check itself and its enforcement at the API boundary.
"""

import io
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend import file_signature, main
from backend.main import app

client = TestClient(app)
FIXTURES_DIR = Path(__file__).resolve().parent

REAL_PDF = (FIXTURES_DIR / "sample_resume.pdf").read_bytes()
REAL_DOCX = (FIXTURES_DIR / "sample_resume.docx").read_bytes()


@pytest.fixture(autouse=True)
def clear_rate_limit():
    main.RATE_LIMIT.clear()
    yield
    main.RATE_LIMIT.clear()


def office_package(*parts):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name in parts:
            archive.writestr(name, "<x/>")
    return buffer.getvalue()


# --------------------------------------------------------------------------
# The content check in isolation
# --------------------------------------------------------------------------

def test_real_fixtures_are_accepted():
    """Guards against a check so strict it rejects genuine uploads."""
    file_signature.verify_upload(REAL_PDF, ".pdf")
    file_signature.verify_upload(REAL_DOCX, ".docx")


IMPOSTORS = [
    ("docx bytes renamed to .pdf", REAL_DOCX, ".pdf"),
    ("pdf bytes renamed to .docx", REAL_PDF, ".docx"),
    ("plain text renamed to .pdf", b"hello world", ".pdf"),
    ("empty file as .pdf", b"", ".pdf"),
    ("empty file as .docx", b"", ".docx"),
    ("zip header but not an archive", b"PK\x03\x04" + bytes(50), ".docx"),
    ("truncated real docx", REAL_DOCX[:200], ".docx"),
    ("pdf magic not at offset 0", b"\x00\x00%PDF-1.4", ".pdf"),
]


@pytest.mark.parametrize(
    "label,content,extension",
    IMPOSTORS,
    # Explicit ids keep binary fixtures out of the generated test name; pytest
    # exports it via PYTEST_CURRENT_TEST, and Windows caps env vars at 32767.
    ids=[case[0] for case in IMPOSTORS],
)
def test_impostors_are_rejected(label, content, extension):
    with pytest.raises(ValueError):
        file_signature.verify_upload(content, extension)


def test_other_office_formats_are_not_accepted_as_docx():
    """A valid Office package is not necessarily a Word document."""
    xlsx_like = office_package("[Content_Types].xml", "xl/workbook.xml")

    assert not file_signature.looks_like_docx(xlsx_like)
    with pytest.raises(ValueError):
        file_signature.verify_upload(xlsx_like, ".docx")


def test_arbitrary_zip_is_not_accepted_as_docx():
    """python-docx raises a bare KeyError on this; it never gets that far now."""
    plain_zip = office_package("hello.txt")

    assert not file_signature.looks_like_docx(plain_zip)


# --------------------------------------------------------------------------
# Enforcement at the API boundary
# --------------------------------------------------------------------------

def post_upload(filename, payload):
    return client.post(
        "/evaluate",
        data={"field": "backend_engineer"},
        files={"file": (filename, payload, "application/octet-stream")},
    )


RENAMED_UPLOADS = [
    ("docx-as-pdf", "resume.pdf", REAL_DOCX),
    ("pdf-as-docx", "resume.docx", REAL_PDF),
    ("text-as-pdf", "resume.pdf", b"not a pdf at all"),
    ("text-as-docx", "resume.docx", b"not a docx at all"),
]


@pytest.mark.parametrize(
    "label,filename,payload",
    RENAMED_UPLOADS,
    ids=[case[0] for case in RENAMED_UPLOADS],
)
def test_renamed_upload_is_rejected_by_the_endpoint(label, filename, payload):
    response = post_upload(filename, payload)

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "unreadable_document"
    assert "extension" in error["message"]


def test_rejection_happens_before_any_temp_file_is_written(monkeypatch):
    """Unverified bytes must not reach the filesystem or a parser."""
    calls = []
    real_tempfile = main.tempfile.NamedTemporaryFile

    def spy(*args, **kwargs):
        calls.append(kwargs.get("suffix"))
        return real_tempfile(*args, **kwargs)

    monkeypatch.setattr(main.tempfile, "NamedTemporaryFile", spy)

    rejected = post_upload("resume.pdf", REAL_DOCX)

    assert rejected.status_code == 422
    assert calls == [], "a temp file was created for an unverified upload"


def test_genuine_uploads_still_reach_the_pipeline():
    for filename, payload in [("resume.pdf", REAL_PDF), ("resume.docx", REAL_DOCX)]:
        main.RATE_LIMIT.clear()
        response = post_upload(filename, payload)

        assert response.status_code == 200, response.text
        assert "heuristic_evaluation" in response.json()
