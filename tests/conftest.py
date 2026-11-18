from __future__ import annotations

import os

import pytest

from tests._ac import COLLECTED_AC_IDS, REPO_ROOT


def pytest_configure(config: pytest.Config) -> None:
    """Drop coverage data left by earlier runs, before any xdist worker starts.

    With pytest-xdist, coverage runs in parallel mode, and `coverage report` combines every
    `.coverage*` file it finds. Stale data would silently raise the reported coverage.
    The controller's own data is still in memory and is written when it exits.
    """
    if os.environ.get("PYTEST_XDIST_WORKER") or "COVERAGE_RUN" not in os.environ:
        return
    for stale in [REPO_ROOT / ".coverage", *REPO_ROOT.glob(".coverage.*")]:
        if stale.is_file():
            stale.unlink()


@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    ids: set[str] = set()
    for item in items:
        for marker in item.iter_markers(name="ac"):
            ids.update(str(arg) for arg in marker.args)
    config.stash[COLLECTED_AC_IDS] = ids
