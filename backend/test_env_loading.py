"""backend/.env must actually reach the application.

backend/.env.example shipped before anything loaded it, so a key written to
backend/.env was silently ignored and every evaluation reported
"Skipped: Missing API Key" while the file sat there looking correct.
"""

import os
from pathlib import Path

from dotenv import dotenv_values, load_dotenv

from backend import main

BACKEND_DIR = Path(__file__).resolve().parent


def test_env_path_points_at_the_backend_env_file():
    """Resolved from the module, so it does not depend on the launch directory."""
    assert main.ENV_PATH == BACKEND_DIR / ".env"
    assert main.ENV_PATH.is_absolute()


def test_example_template_documents_every_variable_the_app_reads():
    """A variable the app reads but the template omits is undiscoverable."""
    template = dotenv_values(BACKEND_DIR / ".env.example")

    assert "GEMINI_API_KEY" in template
    assert "CORS_ORIGINS" in template


def test_example_template_holds_no_real_values():
    """.env.example is tracked in git, so it must never carry a key."""
    template = dotenv_values(BACKEND_DIR / ".env.example")

    for name, value in template.items():
        assert not value, f"{name} has a value in .env.example; it must be blank"


def test_a_real_environment_variable_is_not_overridden_by_the_file(tmp_path, monkeypatch):
    """Explicit environment always wins, so CI and shell exports stay authoritative."""
    env_file = tmp_path / ".env"
    env_file.write_text("RESUME_EVALUATOR_PROBE=from_file\n", encoding="utf-8")

    monkeypatch.setenv("RESUME_EVALUATOR_PROBE", "from_environment")
    load_dotenv(env_file, override=False)

    assert os.environ["RESUME_EVALUATOR_PROBE"] == "from_environment"


def test_the_file_supplies_a_variable_that_is_otherwise_unset(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("RESUME_EVALUATOR_PROBE=from_file\n", encoding="utf-8")

    monkeypatch.delenv("RESUME_EVALUATOR_PROBE", raising=False)
    load_dotenv(env_file, override=False)

    assert os.environ["RESUME_EVALUATOR_PROBE"] == "from_file"


def test_a_missing_env_file_is_not_an_error(tmp_path):
    """Running without backend/.env is the normal case, not a failure."""
    load_dotenv(tmp_path / "does-not-exist.env", override=False)
