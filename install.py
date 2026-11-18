"""Install the Software Factory kit into a git repository.

Usage:
    python install.py check [PATH]

This launcher deliberately uses only syntax that old Python versions can parse, so it can
refuse them with a clear message (E01 AC-03, ADR 0002).
"""

import os
import sys

MIN_VERSION = (3, 11)


def version_ok(version_info=None):
    info = sys.version_info if version_info is None else version_info
    return tuple(info[:2]) >= MIN_VERSION


def run():
    if not version_ok():
        found = tuple(sys.version_info[:2])
        sys.stderr.write(
            "Software Factory needs Python %d.%d or newer; this is Python %d.%d.\n"
            % (MIN_VERSION + found)
        )
        return 1
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from factory_installer import cli

    return cli.main(sys.argv[1:])


if __name__ == "__main__":
    sys.exit(run())
