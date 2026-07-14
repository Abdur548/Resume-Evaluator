import json
from pathlib import Path

import pytest

from backend.job_fit_scorer import score_job_fit


PRESETS_PATH = Path(__file__).resolve().parent / "job_description_presets.json"
with PRESETS_PATH.open("r", encoding="utf-8") as presets_file:
    PRESETS = json.load(presets_file)["presets"]


@pytest.mark.parametrize("preset", PRESETS, ids=lambda preset: preset["id"])
def test_each_preset_extracts_required_and_preferred_requirements(preset):
    result = score_job_fit("", preset["description"], preset["field"])

    assert result["job_fit_score"] == 0
    assert len(result["required"]) >= 5
    assert len(result["preferred"]) >= 2


@pytest.mark.parametrize("preset", PRESETS, ids=lambda preset: preset["id"])
def test_each_preset_scores_deterministically(preset):
    resume_text = preset["description"]

    first = score_job_fit(resume_text, preset["description"], preset["field"])
    second = score_job_fit(resume_text, preset["description"], preset["field"])

    assert first == second
    assert first["job_fit_score"] >= 50
    assert first["missing_required"] == []


def test_ai_preset_uses_unique_capability_groups():
    preset = next(item for item in PRESETS if item["id"] == "ai_ml_engineer")
    result = score_job_fit("", preset["description"], preset["field"])
    skills = [item["skill_term"] for item in result["required"] + result["preferred"]]

    assert len(result["required"]) == 7
    assert len(result["preferred"]) == 4
    assert len(skills) == len(set(skills))
    assert "model_evaluation" in skills
    assert "applied_ai_specialization" in skills
    assert "production_infrastructure" in skills
