"""E16/T1: the `[runner]` config section.

Covers E16 AC-19. Expectations come from the E16 spec ("New config.toml keys") and the design
note ("Config"), not from the implementation.
"""

from __future__ import annotations

import sys
import tomllib
from pathlib import Path

import pytest

from factory_installer import cli, config_schema
from tests._ac import REPO_ROOT
from tests._runner import call, runner_repo

PY = [sys.executable, "-c", "pass"]
RUNNER_DEFAULTS = {
    "max_turns": 50,
    "job_timeout_minutes": 120,
    "max_parallel": 2,
    "worktree_root": "",
}

GOOD = [
    ("max_turns", "1"),
    ("max_turns", "10000"),
    ("job_timeout_minutes", "0.05"),
    ("job_timeout_minutes", "240"),
    ("max_parallel", "1"),
    ("max_parallel", "64"),
    ("worktree_root", '""'),
    ("worktree_root", '"../elsewhere"'),
]
BAD = [
    ("max_turns", "0"),
    ("max_turns", "10001"),
    ("max_turns", "1.5"),
    ("max_turns", "true"),
    ("max_turns", '"50"'),
    ("job_timeout_minutes", "0"),
    ("job_timeout_minutes", "-1"),
    ("job_timeout_minutes", '"x"'),
    ("max_parallel", "0"),
    ("max_parallel", "65"),
    ("worktree_root", "3"),
    ("unknown_key", "1"),
]


def runner_errors(text: str) -> list[str]:
    result = config_schema.validate(tomllib.loads(text))
    return [issue.key for issue in result.errors]


@pytest.mark.ac("E16-AC-19")
def test_runner_section_defaults_match_the_spec() -> None:
    fields = config_schema.SECTIONS["runner"]
    assert {key: field.default for key, field in fields.items()} == RUNNER_DEFAULTS


@pytest.mark.ac("E16-AC-19")
@pytest.mark.parametrize(("key", "value"), GOOD)
def test_good_runner_values_pass(key: str, value: str) -> None:
    assert runner_errors(f"[runner]\n{key} = {value}\n") == []


@pytest.mark.ac("E16-AC-19")
@pytest.mark.parametrize(("key", "value"), BAD)
def test_bad_runner_values_are_errors_naming_the_key(key: str, value: str) -> None:
    assert runner_errors(f"[runner]\n{key} = {value}\n") == [f"runner.{key}"]


@pytest.mark.ac("E16-AC-19")
def test_a_config_without_runner_stays_valid() -> None:
    result = config_schema.validate(tomllib.loads("[budgets]\nper_job_usd = 10\n"))
    assert result.errors == []
    assert {f"runner.{key}" for key in RUNNER_DEFAULTS} <= set(result.missing)


@pytest.mark.ac("E16-AC-19")
def test_the_default_config_has_the_runner_section_with_comments() -> None:
    text = config_schema.render_default()
    section = text.split("[runner]\n", 1)[1].split("\n\n", 1)[0].splitlines()
    assert [line.split(" = ")[0] for line in section] == list(RUNNER_DEFAULTS)
    assert all("  # " in line for line in section), "every key has a comment"
    assert tomllib.loads(text)["runner"] == RUNNER_DEFAULTS
    kit = (REPO_ROOT / "kit" / ".agentic" / "config.toml").read_text(encoding="utf-8")
    assert kit == text


@pytest.mark.ac("E16-AC-19")
def test_install_check_reports_a_bad_runner_value(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / ".agentic").mkdir()
    (tmp_path / ".agentic" / "config.toml").write_text(
        "[runner]\nmax_parallel = 0\n", encoding="utf-8"
    )
    code = cli.main(["check", str(tmp_path)])
    out = capsys.readouterr()
    assert code == 1
    assert "runner.max_parallel" in out.out + out.err


@pytest.mark.ac("E16-AC-19")
def test_this_repo_config_has_the_runner_section() -> None:
    with (REPO_ROOT / ".agentic" / "config.toml").open("rb") as f:
        data = tomllib.load(f)
    assert data["runner"] == RUNNER_DEFAULTS
    assert config_schema.validate(data).errors == []


@pytest.mark.ac("E16-AC-19")
@pytest.mark.parametrize(
    "text",
    [
        *(f"[runner]\n{key} = {value}\n" for key, value in GOOD + BAD),
        "[budgets]\nper_job_usd = 0\n",
        "[budgets]\nper_job_usd = 5\nper_day_usd = 4\n",
        "[budgets]\nwarn_at = 0.9\nhalt_at = 0.8\n",
        "[budgets]\nhalt_at = 1.5\n",
        "[budgets]\nwarn_at = 0.5\nhalt_at = 0.9\n",
        '[gates]\nbase_ref = ""\n',
        '[gates]\nbase_ref = "trunk"\n',
    ],
)
def test_run_py_agrees_with_the_installer_on_what_is_valid(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    text: str,
) -> None:
    """Design note: run.py has its own rules for the keys it reads, pinned to config_schema."""
    read = ("runner.", "budgets.", "gates.base_ref")
    expected_invalid = any(key.startswith(read) for key in runner_errors(text))
    repo = runner_repo(tmp_path, text)
    code, _, err = call(repo, monkeypatch, capsys, "submit", "--", *PY)
    assert code == (2 if expected_invalid else 0), err
