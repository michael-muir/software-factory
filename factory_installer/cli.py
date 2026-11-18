"""Command-line entry point for `python install.py` (E01).

python install.py [PATH] [--dry-run] [--force] [--json]
python install.py check [PATH]
"""

from __future__ import annotations

import argparse
import sys
import tomllib
from collections.abc import Sequence
from pathlib import Path

from factory_installer import config_schema, manifest
from factory_installer.apply import apply, write_file
from factory_installer.kit import KIT_ROOT, load_kit
from factory_installer.plan import MERGE_SUFFIX, manifest_deleted, manifest_files, plan
from factory_installer.report import Report
from factory_installer.target import PathEscapeError, current_hashes, ensure_inside, find_git_root

CONFIG_RELPATH = Path(".agentic") / "config.toml"


def _install_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="install.py",
        description="Install the Software Factory kit into a git repository. "
        "Use 'install.py check [PATH]' to validate .agentic/config.toml.",
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

    if result.errors:
        count = len(result.errors)
        print(f"{shown}: {count} error{'s' if count != 1 else ''}")
        return 1
    print(f"{shown}: OK")
    return 0


def run_install(target: Path, *, kit_root: Path, dry_run: bool, force: bool, as_json: bool) -> int:
    if not target.is_dir():
        print(f"{target}: not a directory; nothing written", file=sys.stderr)
        return 1
    if find_git_root(target) is None:
        print(f"{target}: not inside a git working tree; nothing written", file=sys.stderr)
        return 1

    kit = load_kit(kit_root)
    merge_paths = [rel + MERGE_SUFFIX for rel in kit.files if kit.is_kit_managed(rel)]
    try:
        # Check our own paths before reading anything, then the manifest's untrusted ones.
        ensure_inside(target, [*kit.files, *merge_paths, manifest.MANIFEST_RELPATH])
        previous = manifest.load(target)
        previous_files = previous.files if previous is not None else None
        ensure_inside(target, previous_files or {})
    except PathEscapeError as exc:
        print(f"{exc}. Refusing to write outside {target}; nothing written.", file=sys.stderr)
        return 1

    deleted = previous.deleted if previous is not None else []
    disk = current_hashes(target, {*kit.files, *(previous_files or {})})
    steps = plan(kit, disk, previous_files, deleted=deleted, force=force)
    if not dry_run:
        apply(target, steps)
        new_manifest = manifest.Manifest(
            kit.version, manifest_files(steps, previous_files), manifest_deleted(steps)
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
    args = _install_parser().parse_args(args_list)
    return run_install(
        Path(args.path),
        kit_root=args.kit,
        dry_run=args.dry_run,
        force=args.force,
        as_json=args.json,
    )
