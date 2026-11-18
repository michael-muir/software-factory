"""Command-line entry point for `python install.py` (E01)."""

from __future__ import annotations

import argparse
import sys
import tomllib
from collections.abc import Sequence
from pathlib import Path

from factory_installer import config_schema

CONFIG_RELPATH = Path(".agentic") / "config.toml"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="install.py",
        description="Install the Software Factory kit into a git repository.",
    )
    commands = parser.add_subparsers(dest="command")
    check = commands.add_parser("check", help="validate .agentic/config.toml")
    check.add_argument("path", nargs="?", default=".", help="repository root (default: .)")
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


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "check":
        return run_check(Path(args.path))
    print(
        "install.py: installing the kit arrives in E01/T3; only 'check' works yet.", file=sys.stderr
    )
    return 2
