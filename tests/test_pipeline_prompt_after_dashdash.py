"""E13-T5: the default agent command ends its options with `--` before the prompt.

Claude Code's `--allowedTools` takes any number of values, so without `--` it reads the
prompt as a tool name and the session exits with no prompt (found in the live run on #82).
"""

from __future__ import annotations

import tomllib

import pytest

import pipeline
from factory_installer import config_schema
from tests._ac import REPO_ROOT


def _ends_with_dashdash_prompt(command) -> None:
    command = list(command)
    assert command[-1] == "{prompt}"
    assert command[-2] == "--"
    assert command.count("--") == 1


@pytest.mark.ac("E13-AC-07")
def test_the_pipeline_default_puts_dashdash_before_the_prompt():
    _ends_with_dashdash_prompt(pipeline.PIPELINE_DEFAULTS["agent_command"])


@pytest.mark.ac("E13-AC-07")
def test_the_installer_schema_default_puts_dashdash_before_the_prompt():
    _ends_with_dashdash_prompt(config_schema.AGENT_COMMAND)


@pytest.mark.ac("E13-AC-07")
@pytest.mark.parametrize("config", ["kit/.agentic/config.toml", ".agentic/config.toml"])
def test_the_shipped_config_puts_dashdash_before_the_prompt(config):
    with (REPO_ROOT / config).open("rb") as f:
        data = tomllib.load(f)
    _ends_with_dashdash_prompt(data["pipeline"]["agent_command"])


@pytest.mark.ac("E13-AC-07")
def test_a_session_keeps_the_prompt_as_one_argument_after_dashdash():
    prompt = "You are the spec-writer.\nFollow the skill: spec-interview."
    argv = pipeline.session_argv(
        pipeline.PIPELINE_DEFAULTS["agent_command"], "spec-writer", "Read,Write", prompt
    )
    assert argv[-2:] == ["--", prompt]
    assert argv[argv.index("--allowedTools") + 1] == "Read,Write"
