"""Every acceptance criterion in every spec is covered by a test that names its id.

E01 AC-23 and E05 AC-23. Rewritten in E05/T1 for multi-spec tracing (E05 design note).
"""

from __future__ import annotations

import pytest

from tests._ac import COLLECTED_AC_IDS, all_spec_ac_ids, spec_ac_ids, spec_epics


@pytest.mark.ac("AC-23")
@pytest.mark.ac("E05-AC-23")
def test_specs_found_for_e01_and_e05() -> None:
    assert {"E01", "E05"} <= set(spec_epics())


@pytest.mark.ac("AC-23")
def test_e01_spec_defines_ac_01_to_ac_23() -> None:
    assert spec_ac_ids("E01") == {f"AC-{n:02d}" for n in range(1, 24)}


@pytest.mark.ac("E05-AC-23")
def test_e05_spec_defines_e05_ac_01_to_ac_23() -> None:
    assert spec_ac_ids("E05") == {f"E05-AC-{n:02d}" for n in range(1, 24)}


@pytest.mark.ac("AC-23")
@pytest.mark.ac("E05-AC-23")
def test_every_ac_marker_names_an_ac_in_a_spec(request: pytest.FixtureRequest) -> None:
    unknown = request.config.stash[COLLECTED_AC_IDS] - all_spec_ac_ids()
    assert not unknown, f"tests reference AC ids no spec defines: {sorted(unknown)}"


@pytest.mark.ac("AC-23")
def test_every_e01_ac_has_a_test(request: pytest.FixtureRequest) -> None:
    missing = spec_ac_ids("E01") - request.config.stash[COLLECTED_AC_IDS]
    assert not missing, f"E01 ACs with no test: {sorted(missing)}"


@pytest.mark.ac("E05-AC-23")
def test_every_e05_ac_has_a_test(request: pytest.FixtureRequest) -> None:
    missing = spec_ac_ids("E05") - request.config.stash[COLLECTED_AC_IDS]
    assert not missing, f"E05 ACs with no test: {sorted(missing)}"
