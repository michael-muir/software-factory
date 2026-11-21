"""T2: config.toml defaults (AC-07) and `install.py check` validation (AC-18).

Expected values come from the E01 spec ("config.toml v1 defaults" and "Validation rules"),
not from the implementation.
"""

from __future__ import annotations

import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

from factory_installer import cli, config_schema
from tests._ac import REPO_ROOT

SPEC_DEFAULTS = {
    "schema_version": 1,
    "hosting": {"mode": "local"},
    "budgets": {"per_job_usd": 15, "per_day_usd": 120, "warn_at": 0.8, "halt_at": 1.0},
    "review": {"max_rounds": 3},
    "gates": {
        "coverage_threshold": 0.8,
        "mutation_threshold": 0.6,
        "mutation_scope": "changed-lines",
        "profiles": [],
        "base_ref": "main",
        "commit_checks": ["format", "lint", "types"],
        "python_command": ["python"],
    },
    "models": {"cross_model_vendor": "openai"},
    "adapters": {"tools": ["claude-code", "copilot", "cursor"]},
    "runner": {
        "max_turns": 50,
        "job_timeout_minutes": 120,
        "max_parallel": 2,
        "worktree_root": "",
    },
    "standards": {"packs": {}, "ignore": []},
    "telemetry": {"enabled": False},
}

KIT_CONFIG = REPO_ROOT / "kit" / ".agentic" / "config.toml"


def _repo_with_config(tmp_path: Path, text: str) -> Path:
    (tmp_path / ".agentic").mkdir()
    (tmp_path / ".agentic" / "config.toml").write_text(text, encoding="utf-8")
    return tmp_path


def _default_text_with(old: str, new: str) -> str:
    text = KIT_CONFIG.read_text(encoding="utf-8")
    assert old in text, f"fixture expects {old!r} in the default config"
    return text.replace(old, new, 1)


def _run_check(capsys: pytest.CaptureFixture[str], *args: str) -> tuple[int, str]:
    code = cli.main(["check", *args])
    out = capsys.readouterr()
    return code, out.out + out.err


# --- AC-07: the default config.toml -------------------------------------------------------


@pytest.mark.ac("AC-07")
def test_kit_config_parses_with_tomllib_and_matches_spec_defaults() -> None:
    with KIT_CONFIG.open("rb") as f:
        assert tomllib.load(f) == SPEC_DEFAULTS


@pytest.mark.ac("AC-07")
def test_kit_config_passes_the_validator() -> None:
    with KIT_CONFIG.open("rb") as f:
        result = config_schema.validate(tomllib.load(f))
    assert result.errors == []
    assert result.missing == []


@pytest.mark.ac("AC-07")
def test_rendered_default_is_the_kit_config() -> None:
    assert config_schema.render_default() == KIT_CONFIG.read_text(encoding="utf-8")


# --- AC-18: check command ------------------------------------------------------------------


@pytest.mark.ac("AC-18")
def test_check_valid_config_exits_0(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo = _repo_with_config(tmp_path, KIT_CONFIG.read_text(encoding="utf-8"))
    code, _ = _run_check(capsys, str(repo))
    assert code == 0


@pytest.mark.ac("AC-18")
def test_check_defaults_to_current_directory(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _repo_with_config(tmp_path, "[hosting]\nmode = 'nowhere'\n")
    monkeypatch.chdir(repo)
    code, output = _run_check(capsys)
    assert code == 1
    assert "hosting.mode" in output


@pytest.mark.ac("AC-18")
@pytest.mark.parametrize(
    ("old", "new", "key", "reason"),
    [
        ("[telemetry]", "[budgets.extra]\nx = 1\n\n[telemetry]", "budgets.extra", "unknown"),
        ("enabled = false", "enabled = false\nsurprise = 1", "telemetry.surprise", "unknown"),
        ("per_job_usd = 15", 'per_job_usd = "15"', "budgets.per_job_usd", "expected"),
        ("per_job_usd = 15", "per_job_usd = true", "budgets.per_job_usd", "expected"),
        ("enabled = false", 'enabled = "no"', "telemetry.enabled", "expected"),
        ("max_rounds = 3", "max_rounds = 3.5", "review.max_rounds", "expected"),
        ("per_job_usd = 15", "per_job_usd = -5", "budgets.per_job_usd", "must"),
        ("per_day_usd = 120", "per_day_usd = 0", "budgets.per_day_usd", "must"),
        ("per_job_usd = 15", "per_job_usd = 200", "budgets.per_job_usd", "must"),
        ("warn_at = 0.8", "warn_at = 0.0", "budgets.warn_at", "must"),
        ("warn_at = 0.8", "warn_at = 1.5", "budgets.warn_at", "must"),
        ("halt_at = 1.0", "halt_at = 1.2", "budgets.halt_at", "must"),
        ("max_rounds = 3", "max_rounds = 0", "review.max_rounds", "must"),
        ("max_rounds = 3", "max_rounds = 11", "review.max_rounds", "must"),
        (
            "mutation_threshold = 0.6",
            "mutation_threshold = 1.5",
            "gates.mutation_threshold",
            "must",
        ),
        (
            'mutation_scope = "changed-lines"',
            'mutation_scope = "some"',
            "gates.mutation_scope",
            "must",
        ),
        ('mode = "local"', 'mode = "hybrid"', "hosting.mode", "must"),
        ("[hosting]", '[factory]\nkit_version = "0.1.0"\n\n[hosting]', "factory", "unknown"),
        (
            'cross_model_vendor = "openai"',
            'cross_model_vendor = ""',
            "models.cross_model_vendor",
            "must",
        ),
        ("schema_version = 1", "schema_version = 2", "schema_version", "must"),
    ],
)
def test_check_invalid_config_names_file_key_and_reason(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    old: str,
    new: str,
    key: str,
    reason: str,
) -> None:
    repo = _repo_with_config(tmp_path, _default_text_with(old, new))
    code, output = _run_check(capsys, str(repo))
    assert code == 1
    error_lines = [line for line in output.splitlines() if key in line]
    assert error_lines, f"no output line names {key!r}:\n{output}"
    assert any("config.toml" in line and reason in line.lower() for line in error_lines), output


@pytest.mark.ac("AC-18")
def test_check_reports_every_error_not_just_the_first(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    text = _default_text_with('mode = "local"', 'mode = "hybrid"')
    text = text.replace("max_rounds = 3", "max_rounds = 0", 1)
    repo = _repo_with_config(tmp_path, text)
    code, output = _run_check(capsys, str(repo))
    assert code == 1
    assert "hosting.mode" in output
    assert "review.max_rounds" in output


@pytest.mark.ac("AC-18")
def test_check_allows_missing_keys_and_lists_them(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _repo_with_config(tmp_path, "schema_version = 1\n\n[hosting]\nmode = 'cloud'\n")
    code, output = _run_check(capsys, str(repo))
    assert code == 0
    assert "budgets.per_job_usd" in output
    assert "default" in output.lower()


@pytest.mark.ac("AC-18")
def test_check_invalid_toml_exits_1(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo = _repo_with_config(tmp_path, "[budgets\nper_job_usd = 15\n")
    code, output = _run_check(capsys, str(repo))
    assert code == 1
    assert "config.toml" in output


@pytest.mark.ac("AC-18")
def test_check_missing_config_exits_1(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, output = _run_check(capsys, str(tmp_path))
    assert code == 1
    assert "config.toml" in output


@pytest.mark.ac("AC-18")
@pytest.mark.parametrize(("valid", "expected_code"), [(True, 0), (False, 1)])
def test_install_py_check_command(tmp_path: Path, valid: bool, expected_code: int) -> None:
    text = KIT_CONFIG.read_text(encoding="utf-8")
    if not valid:
        text = text.replace('mode = "local"', 'mode = "hybrid"', 1)
    repo = _repo_with_config(tmp_path, text)
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "install.py"), "check", str(repo)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == expected_code, result.stdout + result.stderr
