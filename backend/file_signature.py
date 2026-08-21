"""Content-based upload verification.

The endpoint used to decide an upload's type from its filename suffix alone, so
any bytes named ``x.pdf`` were handed to pdfplumber and any bytes named
``x.docx`` to python-docx. That put a third-party parser directly behind an
unauthenticated, unvalidated input.

This module answers one question -- "do these bytes actually look like the
format the caller claims?" -- before anything is written to disk or parsed.
"""

import io
import zipfile

PDF_MAGIC = b"%PDF-"

# Every ZIP-based Office package begins with a local file header and must
# contain the content-types part. Checking both distinguishes a real .docx from
# an arbitrary ZIP, which python-docx would otherwise reject with a bare
# KeyError deep inside the library.
ZIP_MAGIC = b"PK\x03\x04"
OFFICE_CONTENT_TYPES = "[Content_Types].xml"

# Word documents are the only Office package this app accepts. A .xlsx or .pptx
# renamed to .docx is a valid ZIP with a valid content-types part, so the
# document part itself is what separates them.
WORD_DOCUMENT_PART = "word/document.xml"

_NOT_A_PDF = (
    "This file is not a PDF. Its contents do not match the .pdf extension."
)
_NOT_A_DOCX = (
    "This file is not a Word document. Its contents do not match the .docx "
    "extension."
)


def looks_like_pdf(content: bytes) -> bool:
    return content.startswith(PDF_MAGIC)


def looks_like_docx(content: bytes) -> bool:
    """True only for a readable ZIP that carries Word's document part."""
    if not content.startswith(ZIP_MAGIC):
        return False
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            names = set(archive.namelist())
    except (zipfile.BadZipFile, OSError, ValueError):
        return False
    return OFFICE_CONTENT_TYPES in names and WORD_DOCUMENT_PART in names


def verify_upload(content: bytes, extension: str) -> None:
    """Raise ValueError when the bytes contradict the claimed extension.

    ``extension`` is the lowercased suffix already validated by the caller.
    """
    if extension == ".pdf":
        if not looks_like_pdf(content):
            raise ValueError(_NOT_A_PDF)
    elif extension == ".docx":
        if not looks_like_docx(content):
            raise ValueError(_NOT_A_DOCX)
    else:
        # Unreachable via the endpoint, which allowlists the suffix first.
        raise ValueError(f"Unsupported file extension '{extension}'.")
