"""E07/T1: gate options --checks and --base-ref, and the two new gates.* config keys.

Covers E07 AC-01, AC-02, AC-03. Expectations come from the E07 spec and design note,
not from the implementation.
"""

from __future__ import annotations

import json
import sys
import tomllib
from pathlib import Path

import pytest

import gate
from factory_installer import cli, config_schema
from tests._ac import REPO_ROOT
from tests._gate import (
    CHECK_ORDER,
    PASS,
    checks_of,
    exits,
    gate_repo,
    git,
    profile,
    run_gate,
    touches,
)

MARKER = {"pyproject.toml": "[project]\nname = 'x'\n"}
KIT_CONFIG = REPO_ROOT / "kit" / ".agentic" / "config.toml"
ECHO = [sys.executable, "-c", "import sys; print('ARGS=' + '|'.join(sys.argv[1:]))"]


def _repo(tmp_path: Path, checks: dict[str, list[str]], config: str | None = None) -> Path:
    return gate_repo(
        tmp_path / "repo",
        {"py.toml": profile("py", ["pyproject.toml"], checks)},
        config=config,
        files=MARKER,
    )


def _json(
    repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    *args: str,
) -> tuple[int, dict[str, object]]:
    monkeypatch.chdir(repo)
    code = gate.main(["--json", *args])
    data = json.loads(capsys.readouterr().out)
    assert isinstance(data, dict)
    return code, data


def _by_check(report: dict[str, object]) -> dict[str, dict[str, object]]:
    return {str(c["check"]): c for c in checks_of(report)}


# --- AC-01: --checks --------------------------------------------------------------------------


@pytest.mark.ac("E07-AC-01")
def test_checks_runs_only_the_named_checks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _repo(
        tmp_path,
        {name: touches(f"ran-{name}.txt") for name in CHECK_ORDER},
    )
    code, report = _json(repo, monkeypatch, capsys, "--checks", "lint,format")
    assert code == 0
    ran = sorted(p.name for p in repo.glob("ran-*.txt"))
    assert ran == ["ran-format.txt", "ran-lint.txt"]
    checks = _by_check(report)
    assert [c["check"] for c in checks_of(report)] == list(CHECK_ORDER)
    for name in CHECK_ORDER:
        if name in ("format", "lint"):
            assert checks[name]["status"] == "pass", name
        else:
            assert checks[name]["status"] == "skipped", name
            assert checks[name]["reason"] == "not selected", name


@pytest.mark.ac("E07-AC-01")
def test_checks_verdict_comes_from_the_selected_checks_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _repo(tmp_path, {"format": PASS, "tests": exits(1)})
    code, report = _json(repo, monkeypatch, capsys, "--checks", "format")
    assert code == 0
    assert report["verdict"] == "pass"
    code, report = _json(repo, monkeypatch, capsys, "--checks", "format,tests")
    assert code == 1
    assert report["verdict"] == "fail"


@pytest.mark.ac("E07-AC-01")
def test_unselected_mutation_never_computes_changed_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _repo(
        tmp_path,
        {"format": PASS, "mutation": [*ECHO, "{changed_files}"]},
        config='[gates]\nbase_ref = "no-such-branch"\n',
    )
    (repo / "new.py").write_text("n = 1\n", encoding="utf-8")
    code, report = _json(repo, monkeypatch, capsys, "--checks", "format")
    assert code == 0, report
    assert _by_check(report)["mutation"]["reason"] == "not selected"


@pytest.mark.ac("E07-AC-01")
def test_unknown_check_name_exits_2_listing_valid_names(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _repo(tmp_path, {"format": touches("ran-format.txt")})
    code, output = run_gate(repo, monkeypatch, capsys, "--checks", "format,typo")
    assert code == 2
    assert "typo" in output
    for name in CHECK_ORDER:
        assert name in output, name
    assert not (repo / "ran-format.txt").exists()


# --- AC-02: --base-ref ------------------------------------------------------------------------


def _feature_repo(tmp_path: Path, config: str | None = None) -> Path:
    repo = _repo(tmp_path, {"mutation": [*ECHO, "{changed_files}"]}, config=config)
    git(repo, "branch", "release")
    git(repo, "checkout", "-q", "-b", "feature")
    (repo / "a.py").write_text("a = 1\n", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "a")
    git(repo, "checkout", "-q", "-b", "later")
    (repo / "b.py").write_text("b = 1\n", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "b")
    return repo


@pytest.mark.ac("E07-AC-02")
def test_base_ref_option_overrides_the_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _feature_repo(tmp_path, config='[gates]\nbase_ref = "release"\n')
    code, report = _json(repo, monkeypatch, capsys)
    assert code == 0
    assert report["changed_files"] == ["a.py", "b.py"]
    code, report = _json(repo, monkeypatch, capsys, "--base-ref", "feature")
    assert code == 0
    assert report["base_ref"] == "feature"
    assert report["changed_files"] == ["b.py"]


@pytest.mark.ac("E07-AC-02")
def test_text_report_shows_the_base_used(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _feature_repo(tmp_path)
    code, output = run_gate(repo, monkeypatch, capsys, "--base-ref", "feature")
    assert code == 0
    assert any("base" in line.lower() and "feature" in line for line in output.splitlines()), output


@pytest.mark.ac("E07-AC-02")
def test_missing_base_ref_option_fails_the_mutation_check_naming_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _feature_repo(tmp_path)
    code, report = _json(repo, monkeypatch, capsys, "--base-ref", "origin/nowhere")
    assert code == 1
    assert "origin/nowhere" in str(_by_check(report)["mutation"]["reason"])


# --- AC-03: config keys -----------------------------------------------------------------------


@pytest.mark.ac("E07-AC-03")
def test_kit_config_shows_both_keys_with_defaults_and_comments() -> None:
    text = KIT_CONFIG.read_text(encoding="utf-8")
    with KIT_CONFIG.open("rb") as f:
        gates = tomllib.load(f)["gates"]
    assert gates["commit_checks"] == ["format", "lint", "types"]
    assert gates["python_command"] == ["python"]
    for key in ("commit_checks", "python_command"):
        line = next(s for s in text.splitlines() if s.startswith(key))
        assert "#" in line, line


@pytest.mark.ac("E07-AC-03")
def test_schema_and_gate_share_the_defaults() -> None:
    schema = config_schema.SECTIONS["gates"]
    assert schema["commit_checks"].default == ["format", "lint", "types"]
    assert schema["python_command"].default == ["python"]
    assert gate.DEFAULTS["commit_checks"] == ["format", "lint", "types"]
    assert gate.DEFAULTS["python_command"] == ["python"]


def _check(tmp_path: Path, capsys: pytest.CaptureFixture[str], gates: str) -> tuple[int, str]:
    (tmp_path / ".agentic").mkdir(parents=True)
    (tmp_path / ".agentic" / "config.toml").write_text(f"[gates]\n{gates}\n", encoding="utf-8")
    code = cli.main(["check", str(tmp_path)])
    out = capsys.readouterr()
    return code, out.out + out.err


@pytest.mark.ac("E07-AC-03")
@pytest.mark.parametrize(
    "gates",
    [
        'commit_checks = ["lint"]',
        "commit_checks = []",
        'commit_checks = ["format", "lint", "types", "build", "tests", "coverage", "mutation"]',
        'python_command = ["uv", "run", "python"]',
    ],
)
def test_valid_values_pass_install_check(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], gates: str
) -> None:
    code, output = _check(tmp_path, capsys, gates)
    assert code == 0, output


@pytest.mark.ac("E07-AC-03")
@pytest.mark.parametrize(
    ("gates", "key"),
    [
        ('commit_checks = ["lint", "typo"]', "gates.commit_checks"),
        ('commit_checks = "lint"', "gates.commit_checks"),
        ("python_command = []", "gates.python_command"),
        ('python_command = "python"', "gates.python_command"),
        ('python_command = ["uv", ""]', "gates.python_command"),
    ],
)
def test_invalid_values_fail_install_check_and_the_gate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    gates: str,
    key: str,
) -> None:
    code, output = _check(tmp_path / "plain", capsys, gates)
    assert code == 1
    assert any(key in line and "config.toml" in line for line in output.splitlines()), output

    repo = _repo(tmp_path, {"format": PASS}, config=f"[gates]\n{gates}\n")
    code, output = run_gate(repo, monkeypatch, capsys)
    assert code == 2
    assert key in output


@pytest.mark.ac("E07-AC-03")
def test_configs_without_the_keys_take_the_defaults(tmp_path: Path) -> None:
    (tmp_path / ".agentic").mkdir()
    (tmp_path / ".agentic" / "config.toml").write_text(
        '[gates]\nmutation_scope = "all"\n', encoding="utf-8"
    )
    settings = gate.Settings.load(tmp_path)
    assert settings.commit_checks == ["format", "lint", "types"]
    assert settings.python_command == ["python"]
