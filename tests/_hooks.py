"""Helpers for hook tests (E07 T2): real git hooks in temp repos, isolated from the user's config.

Every git call gets GIT_CONFIG_GLOBAL pointed at an empty file and GIT_CONFIG_NOSYSTEM=1, so the
developer's own git config is never read or changed (E07 design note, test seams). The venv's
bin directory goes first on PATH, so the hook shims find this interpreter.
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

from tests._ac import REPO_ROOT
from tests._gate import profile, toml_list

INSTALL_PY = REPO_ROOT / "install.py"
VENV_BIN = Path(sys.executable).parent
HOOKS_PATH = ".factory/gates/hooks"
HOOK_NAMES = ("pre-commit", "pre-push")
IDENTITY = ("-c", "user.name=test", "-c", "user.email=test@example.invalid")

# A fixture check: logs its name to LOG, then fails if bad-<name>.txt exists in the cwd.
CHECK_SCRIPT = """\
import pathlib, sys
name, log = sys.argv[1], sys.argv[2]
with open(log, "a", encoding="utf-8") as f:
    f.write(name + "\\n")
sys.exit(1 if pathlib.Path("bad-" + name + ".txt").exists() else 0)
"""

# A python_command wrapper: logs the gate argv to LOG, then runs the gate as __main__.
WRAPPER_SCRIPT = """\
import json, runpy, sys
with open(sys.argv[1], "a", encoding="utf-8") as f:
    f.write("argv " + json.dumps(sys.argv[2:]) + "\\n")
sys.argv = sys.argv[2:]
runpy.run_path(sys.argv[0], run_name="__main__")
"""

FIXTURE_CHECKS = ("format", "lint", "types", "tests")


def isolated_env(tmp_path: Path, path_first: Sequence[Path] = (VENV_BIN,)) -> dict[str, str]:
    home = tmp_path / "git-home"
    home.mkdir(exist_ok=True)
    empty = home / "empty.gitconfig"
    empty.write_text("", encoding="utf-8")
    env = dict(os.environ)
    env["GIT_CONFIG_GLOBAL"] = str(empty)
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    env["PATH"] = os.pathsep.join([*(str(p) for p in path_first), env.get("PATH", "")])
    return env


def run(argv: Sequence[str], cwd: Path, env: Mapping[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(argv), cwd=cwd, env=dict(env), capture_output=True, text=True, check=False
    )


def git(repo: Path, env: Mapping[str, str], *args: str) -> subprocess.CompletedProcess[str]:
    return run(["git", *IDENTITY, *args], repo, env)


def git_ok(repo: Path, env: Mapping[str, str], *args: str) -> str:
    result = git(repo, env, *args)
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout


def install_py(repo: Path, env: Mapping[str, str], *args: str) -> subprocess.CompletedProcess[str]:
    return run([sys.executable, str(INSTALL_PY), *args], repo, env)


def output(result: subprocess.CompletedProcess[str]) -> str:
    return result.stdout + result.stderr


def hooks_path(repo: Path, env: Mapping[str, str]) -> str | None:
    result = git(repo, env, "config", "--local", "--get", "core.hooksPath")
    return result.stdout.strip() if result.returncode == 0 else None


def kit_repo(tmp_path: Path, env: Mapping[str, str], name: str = "repo") -> Path:
    """A git repo on main with the real kit installed and committed; hooks not switched on."""
    repo = tmp_path / name
    repo.mkdir()
    git_ok(repo, env, "init", "-q", "-b", "main")
    result = install_py(repo, env, str(repo))
    assert result.returncode == 0, output(result)
    return repo


class HookRepo:
    """A kit repo with a fixture profile whose checks log to `log` and fail on bad-<name>.txt."""

    def __init__(self, tmp_path: Path, gates: str = "", *, hooks_on: bool = True) -> None:
        self.env = isolated_env(tmp_path)
        self.log = tmp_path / "checks.log"
        self.log.write_text("", encoding="utf-8")
        script = tmp_path / "check.py"
        script.write_text(CHECK_SCRIPT, encoding="utf-8")
        self.wrapper = tmp_path / "wrapper.py"
        self.wrapper.write_text(WRAPPER_SCRIPT, encoding="utf-8")
        self.repo = kit_repo(tmp_path, self.env)
        checks = {
            name: [sys.executable, str(script), name, str(self.log)] for name in FIXTURE_CHECKS
        }
        profiles = self.repo / ".factory" / "gates" / "profiles"
        (profiles / "fx.toml").write_text(profile("fx", ["marker.txt"], checks), encoding="utf-8")
        (self.repo / "marker.txt").write_text("x\n", encoding="utf-8")
        self.write_gates(gates or f"python_command = {toml_list([sys.executable])}")
        git_ok(self.repo, self.env, "add", "-A")
        git_ok(self.repo, self.env, "commit", "-q", "--no-verify", "-m", "fixture")
        if hooks_on:
            result = install_py(self.repo, self.env, "hooks", str(self.repo))
            assert result.returncode == 0, output(result)

    def write_gates(self, gates: str) -> None:
        (self.repo / ".agentic" / "config.toml").write_text(f"[gates]\n{gates}\n", encoding="utf-8")

    def wrapped_command(self) -> str:
        """A python_command that logs the gate argv before running the gate."""
        return toml_list([sys.executable, str(self.wrapper), str(self.log)])

    def logged(self) -> list[str]:
        return self.log.read_text(encoding="utf-8").splitlines()

    def clear_log(self) -> None:
        self.log.write_text("", encoding="utf-8")

    def commit(self, *extra: str) -> subprocess.CompletedProcess[str]:
        (self.repo / "change.txt").write_text(f"{len(self.logged())}\n", encoding="utf-8")
        git_ok(self.repo, self.env, "add", "change.txt")
        return git(self.repo, self.env, "commit", "-m", "change", *extra)

    def head(self) -> str:
        return git_ok(self.repo, self.env, "rev-parse", "HEAD").strip()

    def bare_remote(self, tmp_path: Path) -> Path:
        remote = tmp_path / "remote.git"
        git_ok(tmp_path, self.env, "init", "-q", "--bare", str(remote))
        git_ok(self.repo, self.env, "remote", "add", "origin", str(remote))
        return remote

    def push(self) -> subprocess.CompletedProcess[str]:
        return git(self.repo, self.env, "push", "-q", "origin", "main")


def remote_has_main(remote: Path, env: Mapping[str, str]) -> bool:
    return git(remote, env, "rev-parse", "--verify", "-q", "refs/heads/main").returncode == 0
