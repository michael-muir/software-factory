"""E07/T2: git hooks. The shims, the launcher run_hook.py, and install.py hooks.

Covers E07 AC-04 to AC-08, the local part of AC-16, and AC-17's standard-library rule for the
hook launcher. Hooks run for real through git in temp repos, with the user's git config isolated
(tests/_hooks.py). Expectations come from the E07 spec and design note, not the implementation.
"""

from __future__ import annotations

import ast
import json
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from tests._ac import REPO_ROOT
from tests._gate import toml_list
from tests._hooks import (
    HOOK_NAMES,
    HOOKS_PATH,
    HookRepo,
    git,
    git_ok,
    hooks_path,
    install_py,
    isolated_env,
    kit_repo,
    output,
    remote_has_main,
    run,
)

KIT_HOOKS = REPO_ROOT / "kit" / ".factory" / "gates" / "hooks"
POSIX_ONLY = pytest.mark.skipif(os.name == "nt", reason="exec bits are a no-op on Windows")


def _argv_lines(hr: HookRepo) -> list[list[str]]:
    found: list[list[str]] = []
    for line in hr.logged():
        if line.startswith("argv "):
            value = json.loads(line[len("argv ") :])
            assert isinstance(value, list)
            found.append([str(v) for v in value])
    return found


def _checks_logged(hr: HookRepo) -> list[str]:
    return [line for line in hr.logged() if not line.startswith("argv ")]


# --- AC-04: the shims ---------------------------------------------------------------------------


@pytest.mark.ac("E07-AC-04")
@pytest.mark.parametrize("name", HOOK_NAMES)
def test_kit_ships_each_hook_as_posix_sh_with_lf_endings(name: str) -> None:
    data = (KIT_HOOKS / name).read_bytes()
    assert data.startswith(b"#!/bin/sh\n"), data[:40]
    assert b"\r" not in data
    text = data.decode("utf-8")
    assert "run_hook.py" in text
    assert name in text


@pytest.mark.ac("E07-AC-04")
def test_kit_ships_the_launcher() -> None:
    assert (KIT_HOOKS / "run_hook.py").is_file()


@pytest.mark.ac("E07-AC-04")
@pytest.mark.parametrize("name", HOOK_NAMES)
def test_hooks_are_committed_executable(name: str) -> None:
    for rel in (f"kit/.factory/gates/hooks/{name}", f".factory/gates/hooks/{name}"):
        staged = subprocess.run(
            ["git", "ls-files", "-s", rel],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        assert staged.startswith("100755 "), (rel, staged)


@pytest.mark.ac("E07-AC-04")
@POSIX_ONLY
def test_installer_writes_the_hooks_executable_on_posix(tmp_path: Path) -> None:
    repo = kit_repo(tmp_path, isolated_env(tmp_path))
    for name in HOOK_NAMES:
        mode = (repo / HOOKS_PATH / name).stat().st_mode
        assert mode & stat.S_IXUSR, (name, oct(mode))


# --- AC-05: pre-commit ----------------------------------------------------------------------------


@pytest.mark.ac("E07-AC-05")
def test_pre_commit_runs_the_commit_checks_through_python_command(tmp_path: Path) -> None:
    hr = HookRepo(tmp_path)
    hr.write_gates(f'commit_checks = ["lint", "tests"]\npython_command = {hr.wrapped_command()}')
    git_ok(hr.repo, hr.env, "add", "-A")
    git_ok(hr.repo, hr.env, "commit", "-q", "--no-verify", "-m", "config")
    hr.clear_log()
    before = hr.head()
    result = hr.commit()
    assert result.returncode == 0, output(result)
    assert hr.head() != before
    assert _argv_lines(hr) == [[".factory/gates/gate.py", "--checks", "lint,tests"]]
    assert _checks_logged(hr) == ["lint", "tests"]


@pytest.mark.ac("E07-AC-05")
def test_pre_commit_defaults_to_format_lint_types(tmp_path: Path) -> None:
    hr = HookRepo(tmp_path)
    hr.clear_log()
    result = hr.commit()
    assert result.returncode == 0, output(result)
    assert _checks_logged(hr) == ["format", "lint", "types"]


@pytest.mark.ac("E07-AC-05")
def test_pre_commit_says_unstaged_changes_are_included(tmp_path: Path) -> None:
    hr = HookRepo(tmp_path)
    result = hr.commit()
    assert result.returncode == 0, output(result)
    assert "unstaged" in output(result).lower(), output(result)


@pytest.mark.ac("E07-AC-05")
def test_pre_commit_blocks_when_the_gate_fails(tmp_path: Path) -> None:
    hr = HookRepo(tmp_path)
    (hr.repo / "bad-lint.txt").write_text("x\n", encoding="utf-8")
    before = hr.head()
    result = hr.commit()
    assert result.returncode != 0, output(result)
    assert hr.head() == before
    assert "lint" in output(result)


@pytest.mark.ac("E07-AC-05")
def test_pre_commit_checks_the_working_tree_not_the_index(tmp_path: Path) -> None:
    hr = HookRepo(tmp_path)
    (hr.repo / "bad-format.txt").write_text("never staged\n", encoding="utf-8")
    before = hr.head()
    result = hr.commit()  # stages only change.txt
    assert result.returncode != 0, output(result)
    assert hr.head() == before


@pytest.mark.ac("E07-AC-05")
def test_pre_commit_ignores_checks_outside_commit_checks(tmp_path: Path) -> None:
    hr = HookRepo(tmp_path)
    (hr.repo / "bad-tests.txt").write_text("x\n", encoding="utf-8")
    result = hr.commit()
    assert result.returncode == 0, output(result)
    assert "tests" not in _checks_logged(hr)


@pytest.mark.ac("E07-AC-05")
def test_pre_commit_runs_from_the_repo_root_when_committing_in_a_subfolder(
    tmp_path: Path,
) -> None:
    hr = HookRepo(tmp_path)
    sub = hr.repo / "sub"
    sub.mkdir()
    (sub / "file.txt").write_text("x\n", encoding="utf-8")
    (hr.repo / "bad-types.txt").write_text("x\n", encoding="utf-8")
    git_ok(sub, hr.env, "add", "file.txt")
    result = git(sub, hr.env, "commit", "-m", "from sub")
    assert result.returncode != 0, output(result)


@pytest.mark.ac("E07-AC-05")
def test_missing_python_command_blocks_naming_it(tmp_path: Path) -> None:
    hr = HookRepo(tmp_path)
    hr.write_gates('python_command = ["no-such-python-e07"]')
    git_ok(hr.repo, hr.env, "add", "-A")
    git_ok(hr.repo, hr.env, "commit", "-q", "--no-verify", "-m", "config")
    before = hr.head()
    result = hr.commit()
    assert result.returncode != 0
    assert hr.head() == before
    assert "no-such-python-e07" in output(result)


# --- AC-06: pre-push ----------------------------------------------------------------------------


@pytest.mark.ac("E07-AC-06")
def test_pre_push_runs_the_full_gate_through_python_command(tmp_path: Path) -> None:
    hr = HookRepo(tmp_path)
    hr.write_gates(f"python_command = {hr.wrapped_command()}")
    git_ok(hr.repo, hr.env, "add", "-A")
    git_ok(hr.repo, hr.env, "commit", "-q", "--no-verify", "-m", "config")
    remote = hr.bare_remote(tmp_path)
    hr.clear_log()
    result = hr.push()
    assert result.returncode == 0, output(result)
    assert remote_has_main(remote, hr.env)
    assert _argv_lines(hr) == [[".factory/gates/gate.py"]]
    assert _checks_logged(hr) == ["format", "lint", "types", "tests"]


@pytest.mark.ac("E07-AC-06")
def test_pre_push_blocks_when_the_gate_fails(tmp_path: Path) -> None:
    hr = HookRepo(tmp_path)
    remote = hr.bare_remote(tmp_path)
    (hr.repo / "bad-tests.txt").write_text("x\n", encoding="utf-8")
    git_ok(hr.repo, hr.env, "add", "-A")
    result = git(hr.repo, hr.env, "commit", "-m", "tests fail")  # tests isn't a commit check
    assert result.returncode == 0, output(result)
    result = hr.push()
    assert result.returncode != 0, output(result)
    assert not remote_has_main(remote, hr.env)
    assert "tests" in output(result)


# --- AC-07: finding Python, reading config ------------------------------------------------------


def _sh_only_path(tmp_path: Path) -> tuple[str, Path]:
    """An `sh` to run hooks with, and a PATH directory holding sh but no Python."""
    if os.name == "nt":
        exec_path = Path(
            subprocess.run(
                ["git", "--exec-path"], capture_output=True, text=True, check=True
            ).stdout.strip()
        )
        usr_bin = exec_path.parents[2] / "usr" / "bin"
        sh = usr_bin / "sh.exe"
        assert sh.is_file(), sh
        assert not list(usr_bin.glob("python*")) and not list(usr_bin.glob("py.exe"))
        return str(sh), usr_bin
    bin_dir = tmp_path / "sh-only"
    bin_dir.mkdir()
    sh_path = shutil.which("sh")
    assert sh_path is not None
    (bin_dir / "sh").symlink_to(sh_path)
    return str(bin_dir / "sh"), bin_dir


@pytest.mark.ac("E07-AC-07")
@pytest.mark.parametrize("name", HOOK_NAMES)
def test_hook_without_python_on_path_exits_non_zero_saying_so(tmp_path: Path, name: str) -> None:
    repo = kit_repo(tmp_path, isolated_env(tmp_path))
    sh, bin_dir = _sh_only_path(tmp_path)
    env = dict(os.environ)
    env["PATH"] = str(bin_dir)
    hook = repo / HOOKS_PATH / name
    assert hook.is_file()
    result = run([sh, str(hook)], repo, env)
    assert result.returncode != 0
    assert "python 3.11" in output(result).lower(), output(result)


@pytest.mark.ac("E07-AC-07")
@POSIX_ONLY
def test_hook_skips_a_python3_that_is_not_python(tmp_path: Path) -> None:
    hr = HookRepo(tmp_path)
    fake = tmp_path / "fake-bin"
    fake.mkdir()
    stub = fake / "python3"
    stub.write_text("#!/bin/sh\nexit 9009\n", encoding="utf-8")
    stub.chmod(0o755)
    (fake / "python").symlink_to(sys.executable)
    hr.env["PATH"] = os.pathsep.join([str(fake), hr.env["PATH"]])
    hr.clear_log()
    result = hr.commit()
    assert result.returncode == 0, output(result)
    assert _checks_logged(hr) == ["format", "lint", "types"]


@pytest.mark.ac("E07-AC-07")
@pytest.mark.parametrize(
    ("gates", "key"),
    [
        ('commit_checks = ["lint", "typo"]', "gates.commit_checks"),
        ("python_command = []", "gates.python_command"),
        ("coverage_threshold = 7", "gates.coverage_threshold"),
    ],
)
def test_invalid_config_blocks_with_the_gate_error_naming_the_key(
    tmp_path: Path, gates: str, key: str
) -> None:
    hr = HookRepo(tmp_path)
    hr.write_gates(gates)
    git_ok(hr.repo, hr.env, "add", "-A")
    git_ok(hr.repo, hr.env, "commit", "-q", "--no-verify", "-m", "bad config")
    before = hr.head()
    result = hr.commit()
    assert result.returncode != 0
    assert hr.head() == before
    assert key in output(result), output(result)


# --- AC-08: install.py hooks --------------------------------------------------------------------


@pytest.mark.ac("E07-AC-08")
def test_install_hooks_sets_core_hooks_path(tmp_path: Path) -> None:
    env = isolated_env(tmp_path)
    repo = kit_repo(tmp_path, env)
    result = install_py(repo, env, "hooks", str(repo))
    assert result.returncode == 0, output(result)
    assert hooks_path(repo, env) == HOOKS_PATH


@pytest.mark.ac("E07-AC-08")
def test_install_hooks_defaults_to_the_current_directory(tmp_path: Path) -> None:
    env = isolated_env(tmp_path)
    repo = kit_repo(tmp_path, env)
    result = install_py(repo, env, "hooks")
    assert result.returncode == 0, output(result)
    assert hooks_path(repo, env) == HOOKS_PATH


@pytest.mark.ac("E07-AC-08")
def test_install_hooks_again_reports_already_on(tmp_path: Path) -> None:
    env = isolated_env(tmp_path)
    repo = kit_repo(tmp_path, env)
    assert install_py(repo, env, "hooks", str(repo)).returncode == 0
    result = install_py(repo, env, "hooks", str(repo))
    assert result.returncode == 0, output(result)
    assert "already on" in output(result).lower(), output(result)
    assert hooks_path(repo, env) == HOOKS_PATH


@pytest.mark.ac("E07-AC-08")
def test_install_hooks_refuses_a_foreign_hooks_path_naming_it(tmp_path: Path) -> None:
    env = isolated_env(tmp_path)
    repo = kit_repo(tmp_path, env)
    git_ok(repo, env, "config", "--local", "core.hooksPath", ".husky")
    result = install_py(repo, env, "hooks", str(repo))
    assert result.returncode == 1
    assert ".husky" in output(result)
    assert hooks_path(repo, env) == ".husky"


@pytest.mark.ac("E07-AC-08")
def test_install_hooks_force_replaces_a_foreign_hooks_path(tmp_path: Path) -> None:
    env = isolated_env(tmp_path)
    repo = kit_repo(tmp_path, env)
    git_ok(repo, env, "config", "--local", "core.hooksPath", ".husky")
    result = install_py(repo, env, "hooks", str(repo), "--force")
    assert result.returncode == 0, output(result)
    assert hooks_path(repo, env) == HOOKS_PATH


@pytest.mark.ac("E07-AC-08")
def test_install_hooks_remove_unsets_our_hooks_path(tmp_path: Path) -> None:
    env = isolated_env(tmp_path)
    repo = kit_repo(tmp_path, env)
    assert install_py(repo, env, "hooks", str(repo)).returncode == 0
    result = install_py(repo, env, "hooks", str(repo), "--remove")
    assert result.returncode == 0, output(result)
    assert hooks_path(repo, env) is None


@pytest.mark.ac("E07-AC-08")
def test_install_hooks_remove_leaves_a_foreign_hooks_path(tmp_path: Path) -> None:
    env = isolated_env(tmp_path)
    repo = kit_repo(tmp_path, env)
    git_ok(repo, env, "config", "--local", "core.hooksPath", ".husky")
    result = install_py(repo, env, "hooks", str(repo), "--remove")
    assert result.returncode == 1
    assert ".husky" in output(result)
    assert hooks_path(repo, env) == ".husky"


@pytest.mark.ac("E07-AC-08")
def test_install_hooks_remove_when_off_changes_nothing(tmp_path: Path) -> None:
    env = isolated_env(tmp_path)
    repo = kit_repo(tmp_path, env)
    result = install_py(repo, env, "hooks", str(repo), "--remove")
    assert result.returncode == 0, output(result)
    assert hooks_path(repo, env) is None


@pytest.mark.ac("E07-AC-08")
def test_install_hooks_without_the_kit_says_to_install_first(tmp_path: Path) -> None:
    env = isolated_env(tmp_path)
    repo = tmp_path / "plain"
    repo.mkdir()
    git_ok(repo, env, "init", "-q")
    result = install_py(repo, env, "hooks", str(repo))
    assert result.returncode == 1
    assert "install" in output(result).lower(), output(result)
    assert hooks_path(repo, env) is None


@pytest.mark.ac("E07-AC-08")
def test_install_hooks_outside_a_git_repo_exits_1(tmp_path: Path) -> None:
    env = isolated_env(tmp_path)
    plain = tmp_path / "not-git"
    plain.mkdir()
    result = install_py(plain, env, "hooks", str(plain))
    assert result.returncode == 1, output(result)


@pytest.mark.ac("E07-AC-08")
@POSIX_ONLY
def test_install_hooks_restores_lost_exec_bits(tmp_path: Path) -> None:
    env = isolated_env(tmp_path)
    repo = kit_repo(tmp_path, env)
    for name in HOOK_NAMES:
        (repo / HOOKS_PATH / name).chmod(0o644)
    result = install_py(repo, env, "hooks", str(repo))
    assert result.returncode == 0, output(result)
    for name in HOOK_NAMES:
        assert (repo / HOOKS_PATH / name).stat().st_mode & stat.S_IXUSR, name


# --- AC-17: the launcher is standard library only ----------------------------------------------


@pytest.mark.ac("E07-AC-17")
def test_launcher_imports_only_the_standard_library_and_the_gate() -> None:
    tree = ast.parse((KIT_HOOKS / "run_hook.py").read_text(encoding="utf-8"))
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names += [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.append(node.module)
    top = {name.split(".")[0] for name in names}
    foreign = sorted(n for n in top if n not in sys.stdlib_module_names and n != "gate")
    assert not foreign, foreign
    assert "gate" in top


# --- AC-16 (local): one seeded lint error, the same verdict everywhere ------------------------


@pytest.mark.ac("E07-AC-16")
@pytest.mark.slow
def test_seeded_lint_error_fails_the_gate_and_both_hooks(tmp_path: Path) -> None:
    from tests._profile_fixtures import PYTHON_SEEDS, python_project, statuses, tool_env

    project = python_project(tmp_path / "project")
    env = isolated_env(tmp_path)
    env["PATH"] = tool_env()["PATH"]
    config = project / ".agentic" / "config.toml"
    text = config.read_text(encoding="utf-8")
    seeded = text.replace(
        'python_command = ["python"]', f"python_command = {toml_list([sys.executable])}", 1
    )
    assert seeded != text
    config.write_text(seeded, encoding="utf-8", newline="\n")
    git_ok(project, env, "add", "-A")
    git_ok(project, env, "commit", "-q", "-m", "python_command")
    assert install_py(project, env, "hooks", str(project)).returncode == 0
    remote = tmp_path / "remote.git"
    git_ok(tmp_path, env, "init", "-q", "--bare", str(remote))
    git_ok(project, env, "remote", "add", "origin", str(remote))
    for rel, content in PYTHON_SEEDS["lint"].items():
        (project / rel).write_text(content, encoding="utf-8", newline="\n")

    direct = run([sys.executable, ".factory/gates/gate.py", "--json"], project, env)
    assert direct.returncode == 1, output(direct)
    assert statuses(json.loads(direct.stdout))["lint"] == "fail"

    def lint_failed(text: str) -> bool:
        return any(" lint " in line and " fail " in line for line in text.splitlines())

    git_ok(project, env, "add", "-A")
    before = git_ok(project, env, "rev-parse", "HEAD")
    commit = git(project, env, "commit", "-m", "seed lint error")
    assert commit.returncode != 0, output(commit)
    assert git_ok(project, env, "rev-parse", "HEAD") == before
    assert lint_failed(output(commit)), output(commit)

    git_ok(project, env, "commit", "-q", "--no-verify", "-m", "seed lint error")
    push = git(project, env, "push", "-q", "origin", "main")
    assert push.returncode != 0, output(push)
    assert not remote_has_main(remote, env)
    assert lint_failed(output(push)), output(push)
