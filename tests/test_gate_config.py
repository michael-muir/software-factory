"""E05/T1: the gates.* config keys E05 adds, validated by `install.py check` (E05 AC-20)."""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from factory_installer import cli
from tests._ac import REPO_ROOT

KIT_CONFIG = REPO_ROOT / "kit" / ".agentic" / "config.toml"


def _check(tmp_path: Path, capsys: pytest.CaptureFixture[str], text: str) -> tuple[int, str]:
    (tmp_path / ".agentic").mkdir()
    (tmp_path / ".agentic" / "config.toml").write_text(text, encoding="utf-8")
    code = cli.main(["check", str(tmp_path)])
    out = capsys.readouterr()
    return code, out.out + out.err


def _kit_text_with(old: str, new: str) -> str:
    text = KIT_CONFIG.read_text(encoding="utf-8")
    assert old in text, f"fixture expects {old!r} in the kit config"
    return text.replace(old, new, 1)


@pytest.mark.ac("E05-AC-20")
def test_kit_config_shows_the_new_gate_keys_with_their_defaults() -> None:
    with KIT_CONFIG.open("rb") as f:
        gates = tomllib.load(f)["gates"]
    assert gates["coverage_threshold"] == 0.8
    assert gates["profiles"] == []
    assert gates["base_ref"] == "main"


@pytest.mark.ac("E05-AC-20")
def test_valid_new_gate_keys_pass(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    text = _kit_text_with("profiles = []", 'profiles = ["python", "ts-js"]')
    text = text.replace('base_ref = "main"', 'base_ref = "develop"', 1)
    text = text.replace("coverage_threshold = 0.8", "coverage_threshold = 0.95", 1)
    code, output = _check(tmp_path, capsys, text)
    assert code == 0, output


@pytest.mark.ac("E05-AC-20")
@pytest.mark.parametrize(
    ("old", "new", "key", "reason"),
    [
        (
            "coverage_threshold = 0.8",
            "coverage_threshold = 1.5",
            "gates.coverage_threshold",
            "must",
        ),
        (
            "coverage_threshold = 0.8",
            "coverage_threshold = -0.1",
            "gates.coverage_threshold",
            "must",
        ),
        (
            "coverage_threshold = 0.8",
            'coverage_threshold = "high"',
            "gates.coverage_threshold",
            "expected",
        ),
        ("profiles = []", 'profiles = "python"', "gates.profiles", "expected"),
        ("profiles = []", 'profiles = ["python", 3]', "gates.profiles", "expected"),
        ("profiles = []", 'profiles = ["python", ""]', "gates.profiles", "must"),
        ('base_ref = "main"', 'base_ref = ""', "gates.base_ref", "must"),
        ('base_ref = "main"', "base_ref = 7", "gates.base_ref", "expected"),
    ],
)
def test_invalid_new_gate_keys_name_file_key_and_reason(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    old: str,
    new: str,
    key: str,
    reason: str,
) -> None:
    code, output = _check(tmp_path, capsys, _kit_text_with(old, new))
    assert code == 1
    lines = [line for line in output.splitlines() if key in line]
    assert any("config.toml" in line and reason in line.lower() for line in lines), output


@pytest.mark.ac("E05-AC-20")
def test_older_configs_without_the_new_keys_stay_valid(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, output = _check(tmp_path, capsys, '[gates]\nmutation_scope = "all"\n')
    assert code == 0, output
    for key in ("gates.coverage_threshold", "gates.profiles", "gates.base_ref"):
        assert any(key in line and "default" in line for line in output.splitlines()), key
