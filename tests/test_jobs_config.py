"""E18/T1: the `[jobs]` config section, and `jobs.py` as a kit file this repo installs.

Covers E18 AC-18, and the kit-file part of AC-19. Expectations come from the E18 spec ("New
config.toml keys") and the design note ("Config", "Source layout"), not from the implementation.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from factory_installer import cli, config_schema
from tests._ac import REPO_ROOT
from tests._jobs import call, jobs_repo
from tests._repo import KIT_FILES

JOBS = ".factory/control/jobs.py"
JOBS_DEFAULTS = {"lease_minutes": 10, "daemon_timeout_seconds": 60}

GOOD = [
    ("lease_minutes", "0.05"),
    ("lease_minutes", "10"),
    ("lease_minutes", "1440"),
    ("daemon_timeout_seconds", "5"),
    ("daemon_timeout_seconds", "5.5"),
    ("daemon_timeout_seconds", "3600"),
]
BAD = [
    ("lease_minutes", "0"),
    ("lease_minutes", "-1"),
    ("lease_minutes", '"10"'),
    ("lease_minutes", "true"),
    ("daemon_timeout_seconds", "4.9"),
    ("daemon_timeout_seconds", "0"),
    ("daemon_timeout_seconds", '"60"'),
    ("unknown_key", "1"),
]


def jobs_errors(text: str) -> list[str]:
    result = config_schema.validate(tomllib.loads(text))
    return [issue.key for issue in result.errors]


@pytest.mark.ac("E18-AC-18")
def test_jobs_section_defaults_match_the_spec() -> None:
    fields = config_schema.SECTIONS["jobs"]
    assert {key: field.default for key, field in fields.items()} == JOBS_DEFAULTS


@pytest.mark.ac("E18-AC-18")
@pytest.mark.parametrize(("key", "value"), GOOD)
def test_good_jobs_values_pass(key: str, value: str) -> None:
    assert jobs_errors(f"[jobs]\n{key} = {value}\n") == []


@pytest.mark.ac("E18-AC-18")
@pytest.mark.parametrize(("key", "value"), BAD)
def test_bad_jobs_values_are_errors_naming_the_key(key: str, value: str) -> None:
    assert jobs_errors(f"[jobs]\n{key} = {value}\n") == [f"jobs.{key}"]


@pytest.mark.ac("E18-AC-18")
def test_a_config_without_jobs_stays_valid() -> None:
    result = config_schema.validate(tomllib.loads("[runner]\nmax_turns = 5\n"))
    assert result.errors == []
    assert {f"jobs.{key}" for key in JOBS_DEFAULTS} <= set(result.missing)


@pytest.mark.ac("E18-AC-18")
def test_the_default_config_has_the_jobs_section_with_comments() -> None:
    text = config_schema.render_default()
    section = text.split("[jobs]\n", 1)[1].split("\n\n", 1)[0].splitlines()
    assert [line.split(" = ")[0] for line in section] == list(JOBS_DEFAULTS)
    assert all("  # " in line for line in section), "every key has a comment"
    assert tomllib.loads(text)["jobs"] == JOBS_DEFAULTS
    kit = (REPO_ROOT / "kit" / ".agentic" / "config.toml").read_text(encoding="utf-8")
    assert kit == text


@pytest.mark.ac("E18-AC-18")
def test_install_check_reports_a_bad_jobs_value(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / ".agentic").mkdir()
    (tmp_path / ".agentic" / "config.toml").write_text(
        "[jobs]\nlease_minutes = 0\n", encoding="utf-8"
    )
    code = cli.main(["check", str(tmp_path)])
    out = capsys.readouterr()
    assert code == 1
    assert "jobs.lease_minutes" in out.out + out.err


@pytest.mark.ac("E18-AC-18")
def test_this_repo_config_has_the_jobs_section() -> None:
    with (REPO_ROOT / ".agentic" / "config.toml").open("rb") as f:
        data = tomllib.load(f)
    assert data["jobs"] == JOBS_DEFAULTS
    assert config_schema.validate(data).errors == []


@pytest.mark.ac("E18-AC-18")
@pytest.mark.parametrize("text", [f"[jobs]\n{key} = {value}\n" for key, value in GOOD + BAD])
def test_jobs_py_agrees_with_the_installer_on_what_is_valid(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    text: str,
) -> None:
    """Design note: jobs.py has its own rules for [jobs], pinned to config_schema."""
    expected_invalid = bool(jobs_errors(text))
    repo = jobs_repo(tmp_path, text)
    code, _, err = call(repo, monkeypatch, capsys, "new", "Config check")
    assert code == (2 if expected_invalid else 0), err


@pytest.mark.ac("E18-AC-19")
def test_jobs_py_is_a_kit_file_and_this_repo_commits_its_install() -> None:
    assert JOBS in KIT_FILES
    kit = (REPO_ROOT / "kit" / JOBS).read_bytes().replace(b"\r\n", b"\n")
    installed = (REPO_ROOT / JOBS).read_bytes().replace(b"\r\n", b"\n")
    assert installed == kit, "run install.py . and commit its output"


@pytest.mark.ac("E18-AC-19")
def test_lint_types_tests_and_coverage_take_in_jobs_py() -> None:
    project = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    tool = project["tool"]
    assert "kit/.factory/control" in tool["mypy"]["files"]
    assert tool["mypy"]["strict"] is True
    assert "kit/.factory/control" in tool["pytest"]["ini_options"]["pythonpath"]
    assert "kit/.factory/control" in tool["coverage"]["run"]["source"]
