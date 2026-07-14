# Resume Evaluator

A local full-stack app for deterministic resume scoring, sourced job-profile fit scoring, optional custom job-description analysis, and fallback-safe Gemini supplements.

## Project Layout

```text
Resume_Evaluator/
|-- backend/              FastAPI app, scoring engines, tests, and fixtures
|-- frontend/             Vite React application
|-- progress.md           Build history and current architecture
|-- suggestions.md        Addressed and deferred work
`-- readme.md             Clone-and-run guide
```

The backend is a Python package. Run backend commands from the project root so imports such as `backend.main` resolve consistently. Frontend commands run from `frontend/`.

## Prerequisites

- Python 3.11 or newer
- Node.js 20 or newer with npm

## Environment Variables

`GEMINI_API_KEY` is optional. Without it, deterministic resume and job-fit evaluations still work; the relevant LLM evaluation is returned as `null` with a skip status.

PowerShell:

```powershell
$env:GEMINI_API_KEY="your_api_key_here"
```

macOS/Linux:

```bash
export GEMINI_API_KEY="your_api_key_here"
```

The frontend uses `VITE_API_BASE_URL`, defaulting to `http://localhost:8000`. To override it, create `frontend/.env` from `frontend/.env.example`.

## Backend Setup

From the project root, create the backend virtual environment inside the backend directory and activate it from there:

```powershell
python -m venv backend/.venv
.\backend\.venv\Scripts\Activate.ps1
pip install -r backend/requirements.txt
uvicorn backend.main:app --reload
```

macOS/Linux activation and startup:

```bash
python -m venv backend/.venv
source backend/.venv/bin/activate
pip install -r backend/requirements.txt
uvicorn backend.main:app --reload
```

The API runs at `http://localhost:8000`.

Endpoints:

- `GET /health`
- `GET /fields`
- `GET /job-presets`
- `POST /evaluate` with multipart fields `field`, `file`, and optional `jd_text`

## Frontend Setup

From the project root:

```powershell
cd frontend
npm install
npm run dev
```

The frontend runs at `http://localhost:5173` by default.

## Running the Full App

Use two terminals.

Terminal 1, from the project root:

```powershell
uvicorn backend.main:app --reload
```

Terminal 2:

```powershell
cd frontend
npm run dev
```

Open `http://localhost:5173`, choose one of the built-in job profiles, upload a PDF or DOCX resume under 5 MB, and evaluate it. The selected profile supplies both the scoring field and job description. Choose **Custom job description** to paste a specific employer posting, or turn off **Job-fit analysis** when only the general resume-quality score is needed.

## Tests and Verification

Backend tests, from the project root:

```powershell
python -m pytest backend -v
```

The LLM tests use mocks, so a live Gemini key is not required.

Frontend validation:

```powershell
cd frontend
npm run lint
npm run build
```

## Job Profiles and Job-Fit Evaluation

The app includes five general mid-level profiles:

- AI / Machine Learning Engineer
- Computer Scientist
- Software Engineer
- Data Scientist
- Cybersecurity Analyst

The profiles are maintained in `backend/job_description_presets.json`. They are synthesized and paraphrased from occupation-level sources rather than copied from individual employer advertisements. The primary references are the U.S. Department of Labor's O*NET occupation profiles, the U.S. Bureau of Labor Statistics Occupational Outlook Handbook, and NIST's NICE Workforce Framework for Cybersecurity. Each `/job-presets` record includes its direct source links and occupation codes where available.

The matching synonym clusters live in `backend/field_corpora.json`. A preset's `field` must resolve to one of these corpora or backend startup fails, preventing a preset from silently using the wrong scoring vocabulary.

When `jd_text` is present and non-empty, `/evaluate` keeps the MVP1 keys and adds:

- `job_fit_evaluation`: deterministic evidence-match score, requirement evidence, and capabilities not evidenced in the resume
- `llm_job_fit_evaluation`: optional Gemini qualitative guidance
- `llm_job_fit_evaluation_status`: success, skip, or fallback reason

The deterministic job-fit path does not require Gemini. If `jd_text` is omitted or blank, the response contains no job-fit keys. An empty or unrecognized JD returns `job_fit_score: null` instead of fabricating a score.

The score measures evidence present in the submitted resume; it does not infer that an unevidenced capability is absent from the candidate. Canonical requirements repeated in a description are scored once. A present skill with no stated years or seniority requirement is a full match. When years or seniority are explicitly required, presence starts as partial evidence and comparable resume evidence can complete the match. Required evidence contributes 80% of the aggregate and preferred evidence contributes 20%.

Broad preset alternatives are grouped as capabilities rather than scored as mandatory tool inventories. For example, NLP, computer vision, and generative AI satisfy one AI-specialization group, while AWS, Azure, GCP, Docker, or Kubernetes satisfy one production-infrastructure group.

The frontend is organized as a compact retro workstation. The left evaluation panel contains target, profile, custom-JD, and upload controls. The right document surface previews the selected role and its source register before a run. After evaluation, the same surface switches to **Overview**, **Evidence**, and **Guidance** tabs so large result sets remain scannable without hiding any MVP1 or MVP2 output.

The frontend uses a built-in profile by default and still supports a custom JD. With job-fit analysis enabled, it displays:

- The separate 0-100 resume-evidence match and required/preferred match counts
- Priority tags for required and preferred capabilities not evidenced in the resume
- A split JD/resume evidence board with aligned requirement rows, matched-term highlighting, match percentage, years, and seniority comparisons
- Gemini assessment, gap explanations, and phrasing suggestions when the optional LLM call succeeds
- The selected preset's summary, full requirement text, and source links

The original resume-quality score and Gemini resume supplement remain available in the result tabs alongside job-fit results. Gemini failures never hide deterministic results.

The evidence API records the exact matched resume alias for each canonical capability. This lets the frontend highlight real resume wording such as `Git` for `version_control` or `traffic distribution` for `load_balancing`, rather than highlighting only the internal canonical label.

## Notes

- Supported uploads are PDF and DOCX.
- `/evaluate` rejects uploads over 5 MB.
- `/evaluate` applies an in-memory limit of 10 requests per 60 seconds per client IP.
- CORS currently allows the local frontend origins on ports 3000 and 5173.
- Gemini integration uses the supported `google-genai` SDK through `from google import genai`.
- The frontend limits pasted job descriptions to 20,000 characters.
