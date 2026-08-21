"""Structural regressions for the request pipeline (ARC-01, ARC-02, ARC-03).

These assert *how often* work happens, not how fast it is, so they do not
depend on machine speed. Each pins a defect that was invisible to the
behavioural suite because the output was always correct -- just recomputed:

  ARC-01  The resume was re-scanned once per requirement, and the corpus file
          was re-read from disk on every scan (30 reads per evaluation).
  ARC-02  A request carrying a job description parsed the same upload twice.
  ARC-03  The synchronous pipeline ran on the event loop, so one slow request
          blocked every other one.
"""

import asyncio
import json
import pathlib
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from backend import (
    corpora,
    extract,
    jd_parser,
    job_fit_scorer,
    main,
    pipeline,
    requirement_extractor,
    requirement_matcher,
)
from backend.main import app

FIXTURES_DIR = pathlib.Path(__file__).resolve().parent
REAL_PDF = (FIXTURES_DIR / "sample_resume.pdf").read_bytes()

client = TestClient(app)


@pytest.fixture(autouse=True)
def clear_rate_limit():
    main.RATE_LIMIT.clear()
    yield
    main.RATE_LIMIT.clear()


@pytest.fixture
def software_engineer_preset():
    presets = json.loads(
        (FIXTURES_DIR / "job_description_presets.json").read_text(encoding="utf-8")
    )["presets"]
    return next(p for p in presets if p["id"] == "software_engineer")


# ---------------------------------------------------------------------------
# ARC-01: one resume scan and one corpus read per evaluation
# ---------------------------------------------------------------------------

def test_resume_is_not_rescanned_once_per_requirement(
    monkeypatch, software_engineer_preset
):
    resume = extract.extract_text(str(FIXTURES_DIR / "sample_resume.pdf"))
    jd = software_engineer_preset["description"]
    field = software_engineer_preset["field"]

    calls = []
    real = jd_parser.find_skill_mentions

    def counting(text, requested_field):
        calls.append(len(text))
        return real(text, requested_field)

    for module in (jd_parser, requirement_matcher, requirement_extractor):
        monkeypatch.setattr(module, "find_skill_mentions", counting)

    result = job_fit_scorer.score_job_fit(resume, jd, field)
    requirement_count = len(result["required"]) + len(result["preferred"])

    resume_scans = [size for size in calls if size == len(resume)]

    assert requirement_count > 5, "fixture should produce a realistic requirement set"
    assert len(resume_scans) == 1, (
        f"the resume was scanned {len(resume_scans)} times for "
        f"{requirement_count} requirements; it should be scanned once"
    )


def test_corpus_file_is_read_once_per_process(monkeypatch, software_engineer_preset):
    reads = []
    real_read_text = pathlib.Path.read_text

    def counting_read(self, *args, **kwargs):
        if self.name == "field_corpora.json":
            reads.append(self.name)
        return real_read_text(self, *args, **kwargs)

    monkeypatch.setattr(pathlib.Path, "read_text", counting_read)
    # A true cold start: jd_parser caches alias data derived from the corpus,
    # so clearing only the corpus cache would leave nothing to re-read.
    corpora.reset_all_caches()

    resume = extract.extract_text(str(FIXTURES_DIR / "sample_resume.pdf"))
    jd = software_engineer_preset["description"]
    field = software_engineer_preset["field"]

    job_fit_scorer.score_job_fit(resume, jd, field)
    assert len(reads) == 1, f"corpus read {len(reads)} times in one evaluation"

    job_fit_scorer.score_job_fit(resume, jd, field)
    assert len(reads) == 1, "a second evaluation re-read the corpus from disk"


def test_corpus_cache_can_be_reset():
    """The cache must be droppable, or tests that edit the corpus would lie."""
    first = corpora.load_corpora()
    assert corpora.load_corpora() is first

    corpora.reset_cache()
    assert corpora.load_corpora() is not first


def test_reset_all_caches_also_drops_derived_alias_data():
    """corpora.reset_cache() alone is not enough; this is the footgun it hides."""
    field = "software_engineer"
    before = jd_parser.skill_aliases(field)

    corpora.reset_all_caches()

    assert jd_parser.skill_aliases(field) == before
    assert jd_parser._skill_aliases_cached.cache_info().currsize == 1


# ---------------------------------------------------------------------------
# ARC-02: the upload is parsed once, not once per scorer
# ---------------------------------------------------------------------------

def test_upload_is_extracted_once_even_with_a_job_description(monkeypatch):
    extractions = []
    real_extract = extract.extract_text

    def counting(filepath):
        extractions.append(filepath)
        return real_extract(filepath)

    monkeypatch.setattr(pipeline.extract, "extract_text", counting)

    pipeline.evaluate_upload(
        str(FIXTURES_DIR / "sample_resume.pdf"),
        "software_engineer",
        jd_text="Required\n- Python\n- testing",
    )

    assert len(extractions) == 1, (
        f"the upload was parsed {len(extractions)} times; the resume and "
        "job-fit paths should share one extraction"
    )


def test_resume_only_request_still_extracts_once(monkeypatch):
    extractions = []
    real_extract = extract.extract_text
    monkeypatch.setattr(
        pipeline.extract,
        "extract_text",
        lambda filepath: (extractions.append(filepath), real_extract(filepath))[1],
    )

    pipeline.evaluate_upload(str(FIXTURES_DIR / "sample_resume.pdf"), "software_engineer")

    assert len(extractions) == 1


def test_evaluate_upload_matches_the_separate_entry_points():
    """The extract-once path must produce exactly the old result."""
    path = str(FIXTURES_DIR / "sample_resume.pdf")
    jd = "Required\n- Python\n- testing"

    combined = pipeline.evaluate_upload(path, "software_engineer", jd_text=jd)
    separate = pipeline.evaluate_resume(path, "software_engineer")
    separate.update(pipeline.evaluate_job_fit(path, "software_engineer", jd))

    assert combined == separate


def test_evaluate_upload_omits_job_fit_keys_without_a_description():
    path = str(FIXTURES_DIR / "sample_resume.pdf")

    for blank in (None, "", "   "):
        result = pipeline.evaluate_upload(path, "software_engineer", jd_text=blank)
        assert "job_fit_evaluation" not in result
        assert "heuristic_evaluation" in result


# ---------------------------------------------------------------------------
# ARC-03: a slow request does not block the event loop
# ---------------------------------------------------------------------------

def test_slow_evaluation_does_not_block_other_requests(monkeypatch):
    """Two concurrent requests must overlap rather than serialize.

    The pipeline is synchronous. Run inline on the event loop it would make
    total time ~= 2 x delay; offloaded to the threadpool it overlaps.
    """
    delay = 0.4

    def slow_upload(path, field, jd_text=None):
        time.sleep(delay)
        return {
            "heuristic_evaluation": {"total_score": 75},
            "llm_evaluation": None,
            "llm_evaluation_status": "Skipped: Missing API Key",
        }

    monkeypatch.setattr(main.pipeline, "evaluate_upload", slow_upload)

    async def exercise():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as async_client:
            request = lambda: async_client.post(
                "/evaluate",
                data={"field": "backend_engineer"},
                files={"file": ("resume.pdf", REAL_PDF, "application/pdf")},
            )
            started = time.perf_counter()
            responses = await asyncio.gather(request(), request())
            return time.perf_counter() - started, responses

    elapsed, responses = asyncio.run(exercise())

    assert [r.status_code for r in responses] == [200, 200]
    assert elapsed < delay * 1.8, (
        f"two concurrent requests took {elapsed:.2f}s for a {delay}s workload, "
        "which means they serialized on the event loop"
    )


def test_health_stays_responsive_during_a_slow_evaluation(monkeypatch):
    delay = 0.4

    def slow_upload(path, field, jd_text=None):
        time.sleep(delay)
        return {
            "heuristic_evaluation": {"total_score": 75},
            "llm_evaluation": None,
            "llm_evaluation_status": "Skipped: Missing API Key",
        }

    monkeypatch.setattr(main.pipeline, "evaluate_upload", slow_upload)

    async def exercise():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as async_client:
            evaluation = asyncio.create_task(
                async_client.post(
                    "/evaluate",
                    data={"field": "backend_engineer"},
                    files={"file": ("resume.pdf", REAL_PDF, "application/pdf")},
                )
            )
            await asyncio.sleep(delay / 4)

            started = time.perf_counter()
            health = await async_client.get("/health")
            health_latency = time.perf_counter() - started

            await evaluation
            return health, health_latency

    health, health_latency = asyncio.run(exercise())

    assert health.status_code == 200
    assert health_latency < delay / 2, (
        f"/health took {health_latency:.2f}s while an evaluation was in flight; "
        "the event loop was blocked"
    )
