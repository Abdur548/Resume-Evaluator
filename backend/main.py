import os
import json
import tempfile
import time
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, File, UploadFile, Form, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware

from . import pipeline

app = FastAPI(title="Resume Evaluator API")

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
CORPORA_PATH = Path(__file__).resolve().parent / "field_corpora.json"
with CORPORA_PATH.open("r", encoding="utf-8") as f:
    corpora = json.load(f)
VALID_FIELDS = list(corpora.keys())

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
        raise HTTPException(status_code=429, detail="Too many requests, please try again later.")
    timestamps.append(now)
    RATE_LIMIT[client_ip] = timestamps

    # Validate file type
    if not file.filename.lower().endswith((".pdf", ".docx")):
        raise HTTPException(status_code=400, detail="Invalid file type. Only .pdf and .docx are supported.")

    # Validate field
    if field not in VALID_FIELDS:
        raise HTTPException(status_code=400, detail=f"Invalid field. Valid options are: {', '.join(VALID_FIELDS)}")

    if jd_text is not None and len(jd_text) > MAX_JOB_DESCRIPTION_LENGTH:
        raise HTTPException(
            status_code=413,
            detail=(
                "Job description too large. Maximum allowed length is "
                f"{MAX_JOB_DESCRIPTION_LENGTH:,} characters."
            ),
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
            raise HTTPException(status_code=413, detail="File too large. Maximum allowed size is 5 MB.")

    # Save UploadFile to a temporary file
    suffix = os.path.splitext(file.filename)[1].lower()
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(content)
        tmp_path = tmp.name

    try:
        # Call pipeline
        result = pipeline.evaluate_resume(tmp_path, field)
        if jd_text and jd_text.strip():
            result.update(pipeline.evaluate_job_fit(tmp_path, field, jd_text))
        return result
    except ValueError as e:
        # ValueError raised by extract.py (e.g. scanned/image-only PDF)
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        # Catch any other unexpected errors
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        # Clean up temp file
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
