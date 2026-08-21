r"""
Extraction layer: raw uploaded file -> normalized plain text for scorer.py.

This is the piece that sits between "user uploads a resume" and
score_resume() being called. It does two jobs, and both matter:

1. Get text out of PDF/DOCX at all.
2. Normalize bullet formatting to the "- " prefix scorer.py's regex
   (r"^\s*[•\-\*]\s+") expects -- extraction libraries often flatten
   bullets into plain paragraphs with no marker, which would silently
   zero out the parseability bullet count AND the anti-stuffing gate
   in field_relevance, tanking every score for reasons that have
   nothing to do with resume quality.

Usage:
    from extract import extract_text
    text = extract_text("resume.pdf")   # or "resume.docx"
    result = score_resume(text, field="backend_engineer")
"""

import re
import zipfile
from pathlib import Path

import pdfplumber
from docx import Document
from docx.opc.exceptions import PackageNotFoundError
from pdfplumber.utils.exceptions import PdfminerException

# Unicode bullet characters extraction commonly produces, normalized to "- "
BULLET_CHARS = ["•", "●", "▪", "‣", "◦", "·", "■", "–\t", "*\t"]

SUPPORTED_EXTENSIONS = {".pdf", ".docx"}

# Library-level failures that mean "the caller sent us something unreadable",
# not "the server is broken". They are translated to ValueError so this module
# keeps a single documented error type and callers can map it to a 4xx.
# Note KeyError: python-docx raises it bare when a structurally valid ZIP is
# missing the '[Content_Types].xml' Office part.
_PDF_CORRUPTION_ERRORS = (PdfminerException, zipfile.BadZipFile)
_DOCX_CORRUPTION_ERRORS = (zipfile.BadZipFile, PackageNotFoundError, KeyError)

# Error text is deliberately free of file paths. These messages reach the HTTP
# client, and the path here is a server-side temporary file whose name would
# disclose the host's directory layout and account name.
_UNREADABLE_PDF = (
    "Could not read this file as a PDF. It may be corrupt, incomplete, or not "
    "actually a PDF."
)
_UNREADABLE_DOCX = (
    "Could not read this file as a DOCX. It may be corrupt, incomplete, or not "
    "actually a Word document."
)


def extract_text(filepath: str) -> str:
    """Dispatch by extension. Raises ValueError for unsupported types
    rather than silently returning empty text."""
    path = Path(filepath)
    ext = path.suffix.lower()

    if ext == ".pdf":
        raw = _extract_pdf(path)
    elif ext == ".docx":
        raw = _extract_docx(path)
    else:
        raise ValueError(
            f"Unsupported file type '{ext}'. Supported: {SUPPORTED_EXTENSIONS}"
        )

    return _normalize(raw)


def _extract_pdf(path: Path) -> str:
    lines = []
    try:
        with pdfplumber.open(path) as pdf:
            if len(pdf.pages) == 0:
                raise ValueError("This PDF contains no pages.")
            for page in pdf.pages:
                text = page.extract_text()
                if text:
                    lines.append(text)
    except _PDF_CORRUPTION_ERRORS as exc:
        raise ValueError(_UNREADABLE_PDF) from exc
    if not lines:
        raise ValueError(
            "No extractable text found in this PDF. It is likely a scanned or "
            "image-based document -- this extractor does not do OCR."
        )
    return "\n".join(lines)


def _extract_docx(path: Path) -> str:
    try:
        doc = Document(path)
    except _DOCX_CORRUPTION_ERRORS as exc:
        raise ValueError(_UNREADABLE_DOCX) from exc
    lines = []
    for para in doc.paragraphs:
        text = para.text.strip()
        if not text:
            continue
        # python-docx exposes list formatting via style name, not a
        # unicode bullet character in para.text -- reconstruct it.
        style_name = (para.style.name or "").lower()
        if "list bullet" in style_name or "list paragraph" in style_name:
            lines.append(f"- {text}")
        else:
            lines.append(text)
    if not lines:
        raise ValueError("No text found in this DOCX file.")
    return "\n".join(lines)


def _normalize(text: str) -> str:
    lines = text.split("\n")
    normalized = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            normalized.append("")
            continue

        # Convert known unicode bullet markers at line start to "- "
        replaced = False
        for marker in BULLET_CHARS:
            if stripped.startswith(marker):
                stripped = "- " + stripped[len(marker):].strip()
                replaced = True
                break

        # PDF extraction frequently renders bullet glyphs as font character-ID
        # artifacts like "(cid:127)" instead of a real Unicode bullet -- this
        # is a common failure mode across PDF libraries, not a fixture quirk.
        if not replaced:
            cid_match = re.match(r"^\(cid:\d+\)\s*", stripped)
            if cid_match:
                stripped = "- " + stripped[cid_match.end():].strip()
                replaced = True

        # Some PDF extractions produce bullets as a lone leading dash
        # with no space, or as "o " for sub-bullets -- normalize those too
        if not replaced and re.match(r"^o\s+", stripped):
            stripped = "- " + stripped[2:].strip()

        normalized.append(stripped)

    return "\n".join(normalized)


if __name__ == "__main__":
    import sys
    if len(sys.argv) != 2:
        print("Usage: python extract.py <path_to_resume.pdf_or_docx>")
        sys.exit(1)
    print(extract_text(sys.argv[1]))