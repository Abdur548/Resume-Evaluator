# Suggestions

Last reviewed: 2026-07-14

This file is the decision backlog for Resume Evaluator MVP2. **Addressed** items are implemented and verified. **Deferred** items are intentionally out of the current MVP and include both a reason and a concrete completion condition so they are not ambiguous.

## Priority 1 - Before Public Deployment

- **Upload Content Verification**: Deferred, pre-public hardening - `/evaluate` currently checks filename extensions and size, but not file signatures or internal structure. Complete when PDFs are verified by signature, DOCX uploads are verified as valid Office ZIP packages, malformed files return a safe 400/422 response, and regression fixtures cover renamed or corrupt uploads.
- **Production Rate Limiting**: Deferred, pre-public infrastructure - the current in-memory limit of 10 requests per IP per 60 seconds is adequate for a single local process but is not shared across workers and is reset on restart. Complete when limits use a shared store, trusted-proxy client IP handling is explicit, stale keys expire automatically, and 429 responses include retry metadata.
- **API Error Sanitization**: Deferred, pre-public hardening - unexpected `/evaluate` exceptions currently expose the exception text, which is useful locally but may leak implementation details publicly. Complete when internal errors are logged with a request ID and clients receive a stable generic error schema.
- **LLM Privacy Boundary**: Deferred, pre-public privacy review - phone numbers, national IDs, and simple street addresses are masked, but names, emails, links, and unusual address formats may still reach Gemini. Complete when the product states what is transmitted, masking coverage is test-backed, user consent is explicit where required, and retention behavior is documented.
- **Prompt-Injection Guardrails**: Deferred, pre-public security - regex detection and untrusted-data instructions are adequate for the local MVP but do not constitute a hardened isolation boundary. Complete when a versioned adversarial corpus covers obfuscation and indirect instructions, delimiters are structurally enforced, output handling is reviewed, and fail-closed behavior is tested for both LLM paths.
- **Dense-Prose JD Segmentation**: Deferred, pre-public scoring hardening - the deterministic fallback has one regression test but has not been challenged against enough punctuation-poor or multi-skill prose. Complete when at least ten representative dense-JD fixtures preserve requirement ownership, years, seniority, required/preferred classification, and nearby-skill isolation.
- **Frontend Component Regression Tests**: Deferred, pre-public UI hardening - lint, production builds, browser checks, and live API integration are verified, but there is no dedicated component-test runner. Complete when automated tests cover preset loading, custom-JD mode, upload validation, loading/error states, result-tab switching, evidence gaps, Gemini fallback states, and reset behavior.

## Priority 2 - Product Tuning

- **Job-Fit Seniority Vocabulary**: Deferred, post-MVP2 tuning - the finite basic/mid/senior vocabulary avoids speculative mappings but can miss role-specific wording. Complete when false-negative fixtures justify each added term and tests prove the term attaches only to the nearest requirement or resume skill.
- **Capability Grouping for Other Presets**: Deferred, post-MVP2 tuning - AI alternatives are grouped, while the other presets should change only where adversarial examples show cumulative scoring of genuine alternatives. Complete when each preset has an expected canonical requirement shape and tests demonstrate that interchangeable tools do not multiply the denominator.
- **Preset Calibration Against Hiring Outcomes**: Deferred, post-MVP2 research - current profiles are trustworthy occupational baselines, not validated predictors of interviews or hiring. Complete only with a representative, consented dataset, documented outcome labels, subgroup error analysis, and versioned weight changes.
- **Preset Source Refresh Schedule**: Deferred, post-MVP2 operations - source URLs and provenance are visible but revisions are not monitored. Complete when source metadata includes a checked date and a scheduled job reports changed, redirected, or unavailable O*NET, BLS, and NIST references without silently rewriting profiles.
- **Additional File Types and OCR**: Deferred, post-MVP2 product expansion - PDF and DOCX cover the MVP; TXT, RTF, image resumes, and scanned PDFs add parsing and safety complexity. Complete when user demand identifies the next format and extraction quality, size limits, failure messages, and security tests are defined before enabling it.
- **Preset Library Expansion**: Deferred, post-MVP2 product expansion - the five requested CS profiles cover the current scope. Complete per new role only after authoritative source review, a matching field corpus, unique capability groups, sourced metadata, and deterministic scoring tests are added together.

## Priority 3 - Scale and Operations

- **Installation Preflight**: Deferred, distribution work - the clone-and-run guide is sufficient for developers, while a guided installer would add maintenance cost now. Complete when distribution beyond source checkout requires a command that checks Python, Node, environment variables, occupied ports, and backend/frontend connectivity with actionable errors.
- **BM25 Index Caching**: Deferred, scale-triggered optimization - corpora are small enough that startup and request latency do not justify cache invalidation complexity. Reconsider when benchmarks show corpus construction materially affects p95 evaluation latency or the profile/corpus library grows by an order of magnitude; complete with before/after benchmarks and deterministic cache invalidation.
- **Operational Observability**: Deferred, deployment operations - console output and API statuses are sufficient locally but cannot support production diagnosis. Complete when structured logs capture request IDs, durations, response classes, LLM skip/failure categories, and rate-limit events without resume or JD content.

## Addressed in MVP1/MVP2

- **Configurable CORS**: Addressed - localhost ports 3000 and 5173 remain the safe defaults, while `CORS_ORIGINS` accepts a normalized comma-separated HTTP(S) allowlist for other frontend deployments; credentials, paths, wildcards, queries, and fragments are rejected.
- **Google Generative AI Library Deprecation**: Addressed - both LLM paths use the supported `google-genai` SDK and its client-based API.
- **End-to-End Upload Size Limit**: Addressed - the frontend communicates a 5 MB maximum and `/evaluate` rejects oversized files with HTTP 413 while reading in bounded chunks.
- **End-to-End Job Description Limit**: Addressed - the frontend caps custom JDs at 20,000 characters with a live count, and `/evaluate` now enforces the same limit for direct API callers.
- **Local Endpoint Abuse Protection**: Addressed for MVP - `/evaluate` applies a basic in-memory per-IP limit of 10 requests per 60 seconds; the production replacement remains explicitly tracked above.
- **Required/Preferred Job-Fit Weights**: Addressed for MVP2 - required evidence contributes 80% and preferred evidence 20%, preventing optional specializations from dominating a broad profile.
- **MVP2 Frontend Integration**: Addressed - the frontend submits preset or custom `jd_text` and renders deterministic job fit, priority gaps, aligned requirement evidence, qualifier comparisons, and optional Gemini guidance without replacing MVP1 results.
- **Predefined CS Job Profiles**: Addressed - AI/ML Engineer, Computer Scientist, Software Engineer, Data Scientist, and Cybersecurity Analyst are available through `/job-presets` and selectable in the frontend.
- **Preset Source Reliability**: Addressed - profiles are synthesized from U.S. Department of Labor O*NET profiles, the BLS Occupational Outlook Handbook, and the NIST NICE Workforce Framework, with direct source metadata returned by the API.
- **Custom Employer Job Descriptions**: Addressed - custom mode remains available because occupation profiles cannot represent every employer's stack, domain, and seniority requirements.
- **Duplicate Canonical Requirements**: Addressed - repeated mentions are merged into one scoring row while required placement and the strictest explicit qualifier are retained.
- **Unqualified Match Score Ceiling**: Addressed - an evidenced skill with no stated years or seniority requirement receives full credit; partial credit is reserved for unmet explicit qualifiers.
- **AI Profile Breadth**: Addressed - the AI/ML preset scores seven core capabilities and four optional groups instead of treating every framework, specialization, and infrastructure example as independently mandatory.
- **Resume Evidence Versus Candidate Ability**: Addressed in product semantics - the UI reports evidence demonstrated by the submitted resume and does not claim that an unevidenced capability is absent from the candidate.
- **Retro Workstation UI**: Addressed - the responsive dark terminal evaluator preserves all MVP1/MVP2 states, with restrained phosphor-green text, semantic amber/red accents, profile provenance, compact run metadata, and separate Overview, Evidence, and Guidance views.
