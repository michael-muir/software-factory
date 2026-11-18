"""Command-line entry point for `python install.py` (E01).

python install.py [PATH] [--dry-run] [--force] [--json]
python install.py check [PATH]
python install.py hooks [PATH] [--force] [--remove]
python install.py ci {github|gitlab|azure|jenkins} [PATH] [--os LIST] [--force]
"""

from __future__ import annotations

import argparse
import dataclasses
import importlib.util
import sys
import tomllib
from collections.abc import Sequence
from pathlib import Path

from factory_installer import config_schema, manifest, pipelines
from factory_installer.apply import apply, write_file
from factory_installer.hooks import run_hooks
from factory_installer.kit import KIT_ROOT, load_kit
from factory_installer.plan import MERGE_SUFFIX, manifest_deleted, manifest_files, plan
from factory_installer.report import Report
from factory_installer.target import PathEscapeError, current_hashes, ensure_inside, find_git_root

CONFIG_RELPATH = Path(".agentic") / "config.toml"


def _install_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="install.py",
        description="Install the Software Factory kit into a git repository. "
        "Use 'install.py check [PATH]' to validate .agentic/config.toml, and "
        "'install.py hooks [PATH]' to switch on the git hooks.",
    )
    parser.add_argument("path", nargs="?", default=".", help="target directory (default: .)")
    parser.add_argument("--dry-run", action="store_true", help="show the plan; write nothing")
    parser.add_argument("--force", action="store_true", help="overwrite conflicting kit files")
    parser.add_argument("--json", action="store_true", help="print the report as JSON")
    parser.add_argument("--kit", type=Path, default=KIT_ROOT, help=argparse.SUPPRESS)
    return parser


def _check_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="install.py check", description="Validate .agentic/config.toml."
    )
    parser.add_argument("path", nargs="?", default=".", help="repository root (default: .)")
    return parser


def _hooks_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="install.py hooks",
        description="Switch on the factory git hooks for this clone (sets core.hooksPath).",
    )
    parser.add_argument("path", nargs="?", default=".", help="repository root (default: .)")
    parser.add_argument(
        "--force", action="store_true", help="replace a core.hooksPath set by something else"
    )
    parser.add_argument("--remove", action="store_true", help="switch the factory hooks off again")
    return parser


def _ci_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="install.py ci",
        description="Write a pipeline that runs the gate, set up for the stacks in this repo.",
    )
    parser.add_argument("provider", choices=sorted(pipelines.PROVIDERS), help="CI provider")
    parser.add_argument("path", nargs="?", default=".", help="repository root (default: .)")
    parser.add_argument(
        "--os", help="github only: OSes to run the gate on, e.g. ubuntu,windows,macos"
    )
    parser.add_argument("--force", action="store_true", help="overwrite conflicting files")
    return parser


def _default_options(provider: str) -> dict[str, list[str]]:
    return {"os": list(pipelines.DEFAULT_OS)} if provider == "github" else {}


def run_ci(argv: Sequence[str]) -> int:
    args = _ci_parser().parse_args(argv)
    options: dict[str, list[str]] | None = None
    if args.os is not None:
        if args.provider != "github":
            print(f"--os applies to github only, not {args.provider}", file=sys.stderr)
            return 2
        try:
            options = {"os": list(pipelines.parse_os(args.os))}
        except ValueError as exc:
            print(exc, file=sys.stderr)
            return 2
    code = run_install(
        Path(args.path),
        kit_root=KIT_ROOT,
        dry_run=False,
        force=args.force,
        as_json=False,
        request=(args.provider, options),
    )
    if code == 0:
        print(pipelines.PROVIDERS[args.provider].turn_on)
    return code


def _render_pipelines(
    kit_root: Path, target: Path, recorded: dict[str, dict[str, list[str]]]
) -> dict[str, bytes]:
    rendered: dict[str, bytes] = {}
    for name, options in sorted(recorded.items()):
        spec = pipelines.spec_for(kit_root, target, options)
        rendered[pipelines.PROVIDERS[name].path] = pipelines.render(name, spec).encode("utf-8")
    return rendered


def run_check(repo: Path) -> int:
    config_path = repo / CONFIG_RELPATH
    shown = str(config_path)
    try:
        with config_path.open("rb") as f:
            data = tomllib.load(f)
    except FileNotFoundError:
        print(f"{shown}: not found", file=sys.stderr)
        return 1
    except tomllib.TOMLDecodeError as exc:
        print(f"{shown}: invalid TOML: {exc}", file=sys.stderr)
        return 1

    result = config_schema.validate(data)
    for issue in result.errors:
        print(f"{shown}: {issue.key}: {issue.reason}")
    for key in result.missing:
        default = config_schema.toml_value(config_schema.default_for(key))
        print(f"{shown}: {key}: not set, using default {default}")

    problems = state_problems(repo)
    for problem in problems:
        print(problem)
    if result.errors or problems:
        count = len(result.errors) + len(problems)
        print(f"{shown}: {count} error{'s' if count != 1 else ''}")
        return 1
    print(f"{shown}: OK")
    return 0


def state_problems(repo: Path, kit_root: Path = KIT_ROOT) -> list[str]:
    """The target's state-file problems, from the kit's own state module (E02, ADR 0015)."""
    path = kit_root / ".factory" / "state" / "state.py"
    spec = importlib.util.spec_from_file_location("factory_kit_state", path)
    if spec is None or spec.loader is None:
        return []
    module = importlib.util.module_from_spec(spec)
    sys.modules["factory_kit_state"] = module
    spec.loader.exec_module(module)
    return [str(p) for p in module.validate(repo)]


def run_install(
    target: Path,
    *,
    kit_root: Path,
    dry_run: bool,
    force: bool,
    as_json: bool,
    request: tuple[str, dict[str, list[str]] | None] | None = None,
) -> int:
    if not target.is_dir():
        print(f"{target}: not a directory; nothing written", file=sys.stderr)
        return 1
    if find_git_root(target) is None:
        print(f"{target}: not inside a git working tree; nothing written", file=sys.stderr)
        return 1

    kit = load_kit(kit_root)
    managed = [*(rel for rel in kit.files if kit.is_kit_managed(rel)), *pipelines.PIPELINE_PATHS]
    merge_paths = [rel + MERGE_SUFFIX for rel in managed]
    try:
        # Check our own paths before reading anything, then the manifest's untrusted ones.
        own = [*kit.files, *pipelines.PIPELINE_PATHS, *merge_paths, manifest.MANIFEST_RELPATH]
        ensure_inside(target, own)
        previous = manifest.load(target)
        previous_files = previous.files if previous is not None else None
        ensure_inside(target, previous_files or {})
    except PathEscapeError as exc:
        print(f"{exc}. Refusing to write outside {target}; nothing written.", file=sys.stderr)
        return 1

    recorded = dict(previous.pipelines) if previous is not None else {}
    if request is not None:
        name, options = request
        recorded[name] = (
            options if options is not None else recorded.get(name) or (_default_options(name))
        )
    if recorded:
        try:
            rendered = _render_pipelines(kit_root, target, recorded)
        except pipelines.PipelineError as exc:
            print(f"{target}: {exc}; nothing written", file=sys.stderr)
            return 1
        kit = dataclasses.replace(
            kit, files={**kit.files, **rendered}, extra_managed=frozenset(rendered)
        )

    deleted = previous.deleted if previous is not None else []
    disk = current_hashes(target, {*kit.files, *(previous_files or {})})
    steps = plan(kit, disk, previous_files, deleted=deleted, force=force)
    if not dry_run:
        apply(target, steps)
        new_manifest = manifest.Manifest(
            kit.version,
            manifest_files(steps, previous_files),
            manifest_deleted(steps),
            recorded,
        ).to_bytes()
        manifest_path = target / manifest.MANIFEST_RELPATH
        if not manifest_path.is_file() or manifest_path.read_bytes() != new_manifest:
            write_file(target, manifest.MANIFEST_RELPATH, new_manifest)

    report = Report.from_steps(kit.version, str(target), dry_run, steps)
    print(report.to_json() if as_json else report.to_text())
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args_list = list(sys.argv[1:] if argv is None else argv)
    if args_list[:1] == ["check"]:
        check_args = _check_parser().parse_args(args_list[1:])
        return run_check(Path(check_args.path))
    if args_list[:1] == ["ci"]:
        return run_ci(args_list[1:])
    if args_list[:1] == ["hooks"]:
        hooks_args = _hooks_parser().parse_args(args_list[1:])
        return run_hooks(Path(hooks_args.path), force=hooks_args.force, remove=hooks_args.remove)
    args = _install_parser().parse_args(args_list)
    return run_install(
        Path(args.path),
        kit_root=args.kit,
        dry_run=args.dry_run,
        force=args.force,
        as_json=args.json,
    )
