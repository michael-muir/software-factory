"""AC-23: every acceptance criterion in the E01 spec is covered by a test that names its id."""

from __future__ import annotations

import pytest

from tests._ac import COLLECTED_AC_IDS, spec_ac_ids


@pytest.mark.ac("AC-23")
def test_spec_defines_ac_01_to_ac_23() -> None:
    assert spec_ac_ids() == {f"AC-{n:02d}" for n in range(1, 24)}


@pytest.mark.ac("AC-23")
def test_every_ac_marker_names_an_ac_in_the_spec(request: pytest.FixtureRequest) -> None:
    unknown = request.config.stash[COLLECTED_AC_IDS] - spec_ac_ids()
    assert not unknown, f"tests reference AC ids the spec does not define: {sorted(unknown)}"


@pytest.mark.ac("AC-23")
def test_every_spec_ac_has_a_test(request: pytest.FixtureRequest) -> None:
    missing = spec_ac_ids() - request.config.stash[COLLECTED_AC_IDS]
    assert not missing, f"spec ACs with no test: {sorted(missing)}"
