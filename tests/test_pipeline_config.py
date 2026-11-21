"""E13/T1: the `[pipeline]` config section.

Covers E13 AC-18. Expectations come from the E13 spec ("New config.toml keys", Changes of 21 Nov
2026) and the design note ("Config"): `install.py check` and `pipeline.py` apply the same rules.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

import pipeline
from factory_installer import cli, config_schema
from tests._ac import REPO_ROOT

AC = "E13-AC-18"
DEFAULTS = {
    "checkpoints": ["spec", "merge"],
    "agent_command": [
        "claude",
        "-p",
        "--agent",
        "{role}",
        "--output-format",
        "json",
        "--permission-mode",
        "acceptEdits",
        "--permission-prompts",
        "none",
        "--allowedTools",
        "{allowed_tools}",
        "{prompt}",
    ],
    "forge": "github",
    "gate_retries": 2,
}
GOOD = [
    ("checkpoints", '["spec", "merge"]'),
    ("checkpoints", '["spec", "design", "merge"]'),
    ("checkpoints", '["merge", "design", "spec"]'),
    ("agent_command", '["agent", "{prompt}"]'),
    ("agent_command", '["agent", "--as", "{role}", "--tools", "{allowed_tools}", "{prompt}"]'),
    ("forge", '"github"'),
    ("forge", '"git"'),
    ("gate_retries", "0"),
    ("gate_retries", "5"),
]
BAD = [
    ("checkpoints", '["spec"]'),  # merge is required
    ("checkpoints", '["design", "merge"]'),  # spec is required
    ("checkpoints", '["spec", "merge", "merge"]'),  # a repeat
    ("checkpoints", '["spec", "merge", "deploy"]'),  # unknown
    ("checkpoints", '"spec"'),
    ("agent_command", "[]"),
    ("agent_command", '["agent"]'),  # no {prompt}
    ("agent_command", '["agent", "{prompt}", "{prompt}"]'),  # twice
    ("agent_command", '["agent", "--prompt={prompt}"]'),  # not a whole element
    ("agent_command", '["agent", "{model}", "{prompt}"]'),  # unknown placeholder
    ("agent_command", '["agent", "", "{prompt}"]'),  # an empty item
    ("forge", '"gitlab"'),
    ("forge", "1"),
    ("gate_retries", "-1"),
    ("gate_retries", "6"),
    ("gate_retries", "1.5"),
    ("gate_retries", "true"),
    ("unknown_key", "1"),
]


def schema_errors(text: str) -> list[str]:
    return [issue.key for issue in config_schema.validate(tomllib.loads(text)).errors]


def pipeline_errors(text: str) -> list[str]:
    return [key for key, _reason in pipeline.config_problems(tomllib.loads(text))]


@pytest.mark.ac(AC)
def test_pipeline_section_defaults_match_the_spec() -> None:
    fields = config_schema.SECTIONS["pipeline"]
    assert {key: field.default for key, field in fields.items()} == DEFAULTS
    assert pipeline.PIPELINE_DEFAULTS == DEFAULTS


@pytest.mark.ac(AC)
@pytest.mark.parametrize(("key", "value"), GOOD)
def test_good_values_pass_both_validators(key: str, value: str) -> None:
    text = f"[pipeline]\n{key} = {value}\n"
    assert schema_errors(text) == []
    assert pipeline_errors(text) == []


@pytest.mark.ac(AC)
@pytest.mark.parametrize(("key", "value"), BAD)
def test_bad_values_are_errors_naming_the_key_in_both_validators(key: str, value: str) -> None:
    text = f"[pipeline]\n{key} = {value}\n"
    assert schema_errors(text) == [f"pipeline.{key}"]
    assert pipeline_errors(text) == [f"pipeline.{key}"]


@pytest.mark.ac(AC)
def test_a_config_without_pipeline_stays_valid() -> None:
    result = config_schema.validate(tomllib.loads("[budgets]\nper_job_usd = 10\n"))
    assert result.errors == []
    assert {f"pipeline.{key}" for key in DEFAULTS} <= set(result.missing)
    assert pipeline.config_problems({}) == []
    assert pipeline.pipeline_config({}) == DEFAULTS


@pytest.mark.ac(AC)
def test_pipeline_config_fills_in_defaults_around_given_keys() -> None:
    merged = pipeline.pipeline_config({"pipeline": {"forge": "git"}})
    assert merged == {**DEFAULTS, "forge": "git"}


@pytest.mark.ac(AC)
def test_the_default_config_has_the_pipeline_section_with_comments() -> None:
    text = config_schema.render_default()
    section = text.split("[pipeline]\n", 1)[1].split("\n\n", 1)[0].splitlines()
    assert [line.split(" = ")[0] for line in section] == list(DEFAULTS)
    assert all("  # " in line for line in section), "every key has a comment"
    assert tomllib.loads(text)["pipeline"] == DEFAULTS
    kit = (REPO_ROOT / "kit" / ".agentic" / "config.toml").read_text(encoding="utf-8")
    assert kit == text


@pytest.mark.ac(AC)
def test_install_check_reports_a_bad_pipeline_value(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / ".agentic").mkdir()
    (tmp_path / ".agentic" / "config.toml").write_text(
        '[pipeline]\ncheckpoints = ["spec"]\n', encoding="utf-8"
    )
    code = cli.main(["check", str(tmp_path)])
    out = capsys.readouterr()
    assert code == 1
    assert "pipeline.checkpoints" in out.out + out.err


@pytest.mark.ac(AC)
def test_this_repo_turns_on_the_design_checkpoint() -> None:
    with (REPO_ROOT / ".agentic" / "config.toml").open("rb") as f:
        data = tomllib.load(f)
    assert data["pipeline"] == {**DEFAULTS, "checkpoints": ["spec", "design", "merge"]}
    assert config_schema.validate(data).errors == []
    assert pipeline.config_problems(data) == []
