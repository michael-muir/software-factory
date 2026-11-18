from __future__ import annotations

import pytest

from tests._ac import COLLECTED_AC_IDS


@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    ids: set[str] = set()
    for item in items:
        for marker in item.iter_markers(name="ac"):
            ids.update(str(arg) for arg in marker.args)
    config.stash[COLLECTED_AC_IDS] = ids
