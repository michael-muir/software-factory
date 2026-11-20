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


@pytest.mark.ac("E06-AC-15")
def test_e06_spec_defines_ac_01_to_ac_15_plus_05b() -> None:
    expected = {f"E06-AC-{n:02d}" for n in range(1, 16)} | {"E06-AC-05b", "E06-AC-05c"}
    assert spec_ac_ids("E06") == expected


@pytest.mark.ac("E06-AC-15")
def test_every_e06_ac_has_a_test(request: pytest.FixtureRequest) -> None:
    missing = spec_ac_ids("E06") - request.config.stash[COLLECTED_AC_IDS]
    assert not missing, f"E06 ACs with no test: {sorted(missing)}"


@pytest.mark.ac("E07-AC-17")
def test_e07_spec_defines_ac_01_to_ac_17() -> None:
    assert spec_ac_ids("E07") == {f"E07-AC-{n:02d}" for n in range(1, 18)}


@pytest.mark.ac("E07-AC-17")
def test_every_e07_ac_has_a_test(request: pytest.FixtureRequest) -> None:
    missing = spec_ac_ids("E07") - request.config.stash[COLLECTED_AC_IDS]
    assert not missing, f"E07 ACs with no test: {sorted(missing)}"


@pytest.mark.ac("E02-AC-17")
def test_e02_spec_defines_ac_01_to_ac_17() -> None:
    assert spec_ac_ids("E02") == {f"E02-AC-{n:02d}" for n in range(1, 18)}


@pytest.mark.ac("E02-AC-17")
def test_every_e02_ac_has_a_test(request: pytest.FixtureRequest) -> None:
    missing = spec_ac_ids("E02") - request.config.stash[COLLECTED_AC_IDS]
    assert not missing, f"E02 ACs with no test: {sorted(missing)}"


@pytest.mark.ac("E03-AC-14")
def test_e03_spec_defines_ac_01_to_ac_14() -> None:
    assert spec_ac_ids("E03") == {f"E03-AC-{n:02d}" for n in range(1, 15)}


@pytest.mark.ac("E03-AC-14")
def test_every_e03_ac_has_a_test(request: pytest.FixtureRequest) -> None:
    missing = spec_ac_ids("E03") - request.config.stash[COLLECTED_AC_IDS]
    assert not missing, f"E03 ACs with no test: {sorted(missing)}"


@pytest.mark.ac("E09-AC-11")
def test_e09_spec_defines_ac_01_to_ac_11() -> None:
    assert spec_ac_ids("E09") == {f"E09-AC-{n:02d}" for n in range(1, 12)}


@pytest.mark.ac("E09-AC-11")
def test_every_e09_ac_has_a_test(request: pytest.FixtureRequest) -> None:
    missing = spec_ac_ids("E09") - request.config.stash[COLLECTED_AC_IDS]
    assert not missing, f"E09 ACs with no test: {sorted(missing)}"


@pytest.mark.ac("E10-AC-10")
def test_e10_spec_defines_ac_01_to_ac_10() -> None:
    assert spec_ac_ids("E10") == {f"E10-AC-{n:02d}" for n in range(1, 11)}


@pytest.mark.ac("E10-AC-10")
def test_every_e10_ac_has_a_test(request: pytest.FixtureRequest) -> None:
    missing = spec_ac_ids("E10") - request.config.stash[COLLECTED_AC_IDS]
    assert not missing, f"E10 ACs with no test: {sorted(missing)}"


@pytest.mark.ac("E12-AC-12")
def test_e12_spec_defines_ac_01_to_ac_12() -> None:
    assert spec_ac_ids("E12") == {f"E12-AC-{n:02d}" for n in range(1, 13)}


@pytest.mark.ac("E12-AC-12")
def test_every_e12_ac_but_the_live_check_has_a_test(request: pytest.FixtureRequest) -> None:
    # AC-11 is the product owner's live check in each tool; the PR records what they saw.
    missing = spec_ac_ids("E12") - {"E12-AC-11"} - request.config.stash[COLLECTED_AC_IDS]
    assert not missing, f"E12 ACs with no test: {sorted(missing)}"
