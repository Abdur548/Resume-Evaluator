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
- Node.js `^20.19` or `>=22.12` with npm — the exact range required by `vite`, `@vitejs/plugin-react`, and `oxlint`. Node 20.0 through 20.18 will not build.

`backend/.venv` is the canonical backend environment. Create it from the project
root exactly as shown below; running `python -m venv backend/.venv` from inside
`backend/` produces a stray `backend/backend/.venv` instead. CI installs from
`backend/requirements.txt` and fails if any installed version drifts from a pin,
so a local environment that disagrees with the manifest will not match CI.

## Environment Variables

`GEMINI_API_KEY` is optional. Without it, deterministic resume and job-fit evaluations still work; the relevant LLM evaluation is returned as `null` with a skip status.

`GROQ_API_KEY` is an optional fallback. When it is set and a Gemini call fails for any reason — capacity (`503`), rate limit, a retired model (`404`), or an invalid key — the request is immediately retried against Groq instead. Falling back on *any* failure is deliberate: a second provider with its own key and model covers the cases a retry against Gemini could not fix. With no Groq key set, behaviour is unchanged.

A fallback answer is visible in the status string, because it came from a different model:

```text
Success                                              Gemini answered
Success via Groq (Gemini: Service unavailable)       fallback answered
Failed: Gemini: Rate limit exceeded; Groq: Timeout   neither answered
```

Deterministic scores are never affected — a provider outage can only remove the optional Gemini/Groq panels, never a score.

`GEMINI_MODEL` and `GROQ_MODEL` override the pinned defaults in `backend/llm_providers.py`. Hosted models get retired periodically; to see what your keys can currently reach:

```powershell
python -m backend.llm_providers
```

`CORS_ORIGINS` is optional. It accepts a comma-separated list of HTTP(S) origins and defaults to `http://localhost:3000,http://localhost:5173`. Use it when the frontend runs on another origin; do not include credentials, paths, wildcards, queries, or fragments.

PowerShell:

```powershell
$env:GEMINI_API_KEY="your_api_key_here"
$env:CORS_ORIGINS="http://localhost:5173,https://resume.example.com"
```

macOS/Linux:

```bash
export GEMINI_API_KEY="your_api_key_here"
export CORS_ORIGINS="http://localhost:5173,https://resume.example.com"
```

The frontend uses `VITE_API_BASE_URL`, defaulting to `http://localhost:8000`. To override it, create `frontend/.env` from `frontend/.env.example`.

Backend variables can also go in `backend/.env`, which is loaded automatically when the backend starts. **Copy** `backend/.env.example` to `backend/.env` rather than renaming it, so the template stays in the repo:

```powershell
Copy-Item backend/.env.example backend/.env
```

A variable already present in the environment always wins over the file, so an explicit `$env:GEMINI_API_KEY` or a CI secret is never overridden by a stale `.env`.

Every `.env` file is gitignored; the `.env.example` templates are not, so keep real keys out of them. If a key in `backend/.env` appears to have no effect, confirm the backend was restarted after the file changed — the file is read once at startup, and `--reload` only watches source files.

## Data sent to Gemini

**Without `GEMINI_API_KEY`, nothing leaves your machine.** Extraction, resume scoring, and job-fit matching are entirely local and deterministic. The two Gemini supplements return `null` with a skip status and no network call is made.

**With `GEMINI_API_KEY` set, the full text of every resume you evaluate is sent to Google's Gemini API**, along with the job description and the deterministic result. This happens on every evaluation, using your own API key, and the data is then handled under whatever terms apply to your own Google account. This project neither stores nor forwards it anywhere else.

The backend applies some redaction before the call, but **it is partial and you should not rely on it**:

| | Redacted before sending |
|---|---|
| Phone numbers, US-format SSNs, simple street addresses | Yes, in the resume and job-description text |
| Names, email addresses, LinkedIn/GitHub URLs | **No** |
| Unusual address formats, dates of birth, employer names | **No** |

There is also one path around the redaction entirely. The deterministic job-fit result is sent alongside the resume, and it embeds verbatim resume lines as match evidence. Those lines are **not** redacted, so a detail that would otherwise be masked still reaches Gemini when it shares a line with a matched skill — a contact line such as `Jane Doe - Python Engineer - (555) 123-4567` is sent as written.

This is a deliberate trade-off for a local, bring-your-own-key tool: your resumes go to your own Gemini account, and you decide whether that is acceptable. Two things follow from it:

- Leave `GEMINI_API_KEY` unset if you do not want resume text sent anywhere. Every score except the two optional Gemini panels still works.
- Do not evaluate someone else's resume with a key set unless they know their resume will be sent to a third-party API.

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

Backend tests, from the project root with `backend/.venv` activated:

```powershell
python -m pytest backend -v
```

To confirm the active environment matches the pinned manifest — the same check CI runs:

```powershell
python .github/scripts/check_pins.py
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

The frontend is organized as a compact dark terminal workstation with near-black surfaces, restrained phosphor-green text, and semantic amber/red status accents. The left evaluation panel contains target, profile, custom-JD, and upload controls. The right document surface previews the selected role and its source register before a run. After evaluation, the same surface switches to **Overview**, **Evidence**, and **Guidance** tabs so large result sets remain scannable without hiding any MVP1 or MVP2 output.

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
- `/evaluate` rejects job descriptions over 20,000 characters, matching the frontend input limit.
- `/evaluate` applies an in-memory limit of 10 requests per 60 seconds per client IP.
- CORS allows local frontend ports 3000 and 5173 by default and can be configured with `CORS_ORIGINS`.
- Gemini integration uses the supported `google-genai` SDK through `from google import genai`.
- The frontend limits pasted job descriptions to 20,000 characters.
