import json
import logging
import os
import tempfile
import time
import uuid
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, File, UploadFile, Form, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from . import corpora, file_signature, pipeline

logger = logging.getLogger("resume_evaluator")

app = FastAPI(title="Resume Evaluator API")


# ---------------------------------------------------------------------------
# Error handling
#
# Every error response has the same shape, so the client never has to guess
# whether `detail` is a string or FastAPI's validation array:
#
#     {"error": {"code": str, "message": str, "request_id": str}}
#
# `message` is always safe to display. Internal exception text is logged
# server-side against the request id and never sent to the client.
# ---------------------------------------------------------------------------
class ApiError(HTTPException):
    """An error whose message is intended for the caller to read."""

    def __init__(self, status_code: int, code: str, message: str):
        super().__init__(status_code=status_code, detail=message)
        self.code = code
        self.message = message


def _request_id(request: Request) -> str:
    return getattr(request.state, "request_id", "unknown")


def _error_response(request: Request, status: int, code: str, message: str) -> JSONResponse:
    request_id = _request_id(request)
    return JSONResponse(
        status_code=status,
        content={
            "error": {"code": code, "message": message, "request_id": request_id}
        },
        headers={"X-Request-ID": request_id},
    )


@app.middleware("http")
async def assign_request_id(request: Request, call_next):
    """Tag every request so a client-visible error maps to one server log line."""
    request.state.request_id = uuid.uuid4().hex[:12]
    response = await call_next(request)
    response.headers["X-Request-ID"] = request.state.request_id
    return response


@app.exception_handler(ApiError)
async def handle_api_error(request: Request, exc: ApiError) -> JSONResponse:
    return _error_response(request, exc.status_code, exc.code, exc.message)


@app.exception_handler(HTTPException)
async def handle_http_exception(request: Request, exc: HTTPException) -> JSONResponse:
    """Normalize any bare HTTPException into the standard envelope."""
    code = "http_error"
    if exc.status_code == 404:
        code = "not_found"
    elif exc.status_code == 405:
        code = "method_not_allowed"
    message = exc.detail if isinstance(exc.detail, str) else "Request failed."
    return _error_response(request, exc.status_code, code, message)


@app.exception_handler(RequestValidationError)
async def handle_validation_error(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """FastAPI's validation array is replaced by one readable sentence.

    The raw array names internal parameter locations, and the frontend renders
    `detail` directly -- previously showing '[object Object]' for this case.
    """
    fields = sorted({str(err["loc"][-1]) for err in exc.errors() if err.get("loc")})
    named = ", ".join(fields) if fields else "the submitted form"
    logger.info(
        "request %s failed validation: %s", _request_id(request), exc.errors()
    )
    return _error_response(
        request,
        422,
        "invalid_request",
        f"The request is missing or has an invalid value for: {named}.",
    )


@app.exception_handler(Exception)
async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
    """Log the real cause, return nothing about it."""
    request_id = _request_id(request)
    logger.exception("request %s failed unexpectedly", request_id)
    return _error_response(
        request,
        500,
        "internal_error",
        "The server could not complete this request. Quote the request id when "
        "reporting the problem.",
    )

# Simple in-memory rate limiting (IP based)
RATE_LIMIT = {}
RATE_LIMIT_WINDOW = 60  # seconds
RATE_LIMIT_MAX = 10  # max requests per window per IP

MAX_FILE_SIZE = 5 * 1024 * 1024  # 5 MB
MAX_JOB_DESCRIPTION_LENGTH = 20_000
READ_CHUNK_SIZE = 1024 * 1024

DEFAULT_CORS_ORIGINS = (
    "http://localhost:3000",
    "http://localhost:5173",
)


def parse_cors_origins(raw_origins: str | None) -> list[str]:
    """Return a normalized CORS allowlist without accepting paths or wildcards."""
    if raw_origins is None or not raw_origins.strip():
        return list(DEFAULT_CORS_ORIGINS)

    origins = []
    for candidate in raw_origins.split(","):
        parsed = urlsplit(candidate.strip().rstrip("/"))
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.netloc
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path
            or parsed.query
            or parsed.fragment
        ):
            raise RuntimeError(
                "CORS_ORIGINS must contain comma-separated HTTP(S) origins "
                "without paths, queries, or fragments."
            )
        origin = f"{parsed.scheme.lower()}://{parsed.netloc.lower()}"
        if origin not in origins:
            origins.append(origin)
    return origins


CORS_ORIGINS = parse_cors_origins(os.environ.get("CORS_ORIGINS"))

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Load fields relative to this module, independent of the launch directory.
VALID_FIELDS = corpora.available_fields()

PRESETS_PATH = Path(__file__).resolve().parent / "job_description_presets.json"
with PRESETS_PATH.open("r", encoding="utf-8") as f:
    JOB_PRESETS = json.load(f)["presets"]

_preset_ids = [preset["id"] for preset in JOB_PRESETS]
if len(_preset_ids) != len(set(_preset_ids)):
    raise RuntimeError("Job-description preset IDs must be unique.")
for preset in JOB_PRESETS:
    if preset["field"] not in VALID_FIELDS:
        raise RuntimeError(
            f"Preset {preset['id']} references unknown field {preset['field']}."
        )

@app.get("/health")
def health_check():
    return {"status": "ok"}

@app.get("/fields")
def get_fields():
    return {"fields": VALID_FIELDS}


@app.get("/job-presets")
def get_job_presets():
    return {"presets": JOB_PRESETS}

@app.post("/evaluate")
async def evaluate(
    request: Request,
    field: str = Form(...),
    file: UploadFile = File(...),
    jd_text: str | None = Form(None),
):
    # Simple rate limiting based on client IP
    client_ip = request.client.host if request.client else "unknown"
    now = int(time.time())
    window_start = now - RATE_LIMIT_WINDOW
    timestamps = RATE_LIMIT.get(client_ip, [])
    # Remove timestamps outside the current window
    timestamps = [ts for ts in timestamps if ts > window_start]
    if len(timestamps) >= RATE_LIMIT_MAX:
        raise ApiError(
            429, "rate_limited", "Too many requests, please try again later."
        )
    timestamps.append(now)
    RATE_LIMIT[client_ip] = timestamps

    # Validate file type
    if not (file.filename or "").lower().endswith((".pdf", ".docx")):
        raise ApiError(
            400,
            "invalid_file_type",
            "Invalid file type. Only .pdf and .docx are supported.",
        )

    # Validate field
    if field not in VALID_FIELDS:
        raise ApiError(
            400,
            "invalid_field",
            f"Invalid field. Valid options are: {', '.join(VALID_FIELDS)}",
        )

    if jd_text is not None and len(jd_text) > MAX_JOB_DESCRIPTION_LENGTH:
        raise ApiError(
            413,
            "job_description_too_large",
            "Job description too large. Maximum allowed length is "
            f"{MAX_JOB_DESCRIPTION_LENGTH:,} characters.",
        )

    # Read in bounded chunks so oversized uploads are rejected before the
    # application keeps the entire body in memory.
    content = bytearray()
    while True:
        chunk = await file.read(READ_CHUNK_SIZE)
        if not chunk:
            break
        content.extend(chunk)
        if len(content) > MAX_FILE_SIZE:
            raise ApiError(
                413, "file_too_large", "File too large. Maximum allowed size is 5 MB."
            )

    suffix = os.path.splitext(file.filename)[1].lower()

    # Confirm the bytes match the claimed extension before anything is written
    # to disk or handed to a parser. Rejecting here keeps renamed and corrupt
    # files away from pdfplumber and python-docx entirely.
    try:
        file_signature.verify_upload(bytes(content), suffix)
    except ValueError as e:
        raise ApiError(422, "unreadable_document", str(e)) from e

    # Save UploadFile to a temporary file
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(content)
        tmp_path = tmp.name

    try:
        # The pipeline is synchronous and slow: PDF parsing, BM25 scoring and
        # up to four Gemini round trips. Running it inline would block the
        # event loop for the whole request, so a single slow LLM call would
        # stall every other in-flight request including /health.
        result = await run_in_threadpool(
            pipeline.evaluate_upload, tmp_path, field, jd_text
        )
        return result
    except ValueError as e:
        # extract.py raises ValueError for every unreadable-document case,
        # including corrupt PDFs and DOCXs that used to surface as a 500.
        # Its messages are caller-facing and carry no server paths.
        raise ApiError(422, "unreadable_document", str(e)) from e
    finally:
        # Clean up temp file. A failure here does not affect the response, but
        # it must not vanish silently -- a leaked temp file holds resume text.
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                logger.warning(
                    "request %s could not remove its temporary upload",
                    _request_id(request),
                    exc_info=True,
                )
