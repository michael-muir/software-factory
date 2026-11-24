"""E31/T1: `trace_file` reads Python test files with `tokenize` and binds tags only from real
markers: comments (to the next test), `@pytest.mark.ac(...)` (to the decorated test) and a test's
docstring (to that test). Tags in any other string bind to nothing (ADR 0054).

Covers E31 AC-01, AC-02, AC-03 (Python), AC-05, AC-06 (Python), AC-07 and AC-08. Expectations come
from the E31 spec and design note, not from the implementation. The inline fixtures use a made-up
epic, E42, so that drafting E31's own PRs doesn't trace the tags these fixtures hold.
"""

from __future__ import annotations

import subprocess
import tomllib

import pytest

import evidence
from tests._ac import REPO_ROOT

EPIC = "E42"
PATH = "tests/test_widgets.py"


def trace(source: str) -> dict[str, list[str]]:
    return evidence.trace_file(PATH, source, EPIC).acs


@pytest.mark.ac("E31-AC-01")
def test_tag_in_a_plain_string_binds_to_no_test() -> None:
    source = (
        "COVERED = ['E42-AC-01', 'E42-AC-02']\n"
        "\n"
        "\n"
        "def test_coverage() -> None:\n"
        "    assert COVERED\n"
    )
    assert trace(source).get("AC-01", []) == []
    assert trace(source).get("AC-02", []) == []


@pytest.mark.ac("E31-AC-01")
def test_tag_in_a_string_inside_a_test_body_binds_to_no_test() -> None:
    source = (
        "def test_first() -> None:\n"
        "    assert 'E42-AC-03' != ''\n"
        "\n"
        "\n"
        "def test_second() -> None:\n"
        "    pass\n"
    )
    assert trace(source).get("AC-03", []) == []


@pytest.mark.ac("E31-AC-01")
def test_tag_in_a_triple_quoted_module_string_binds_to_no_test() -> None:
    source = (
        '"""Module notes that mention E42-AC-04."""\n'
        "\n"
        "FIXTURE = '''\n"
        "E42-AC-05\n"
        "'''\n"
        "\n"
        "\n"
        "def test_after() -> None:\n"
        "    pass\n"
    )
    acs = trace(source)
    assert acs.get("AC-04", []) == []
    assert acs.get("AC-05", []) == []


@pytest.mark.ac("E31-AC-02")
def test_ac_mark_binds_to_the_decorated_test() -> None:
    source = 'import pytest\n\n\n@pytest.mark.ac("E42-AC-01")\ndef test_add() -> None:\n    pass\n'
    assert trace(source)["AC-01"] == ["test_add"]


@pytest.mark.ac("E31-AC-02")
def test_ac_mark_with_several_ids_binds_each_to_the_decorated_test() -> None:
    source = (
        "import pytest\n"
        "\n"
        "\n"
        '@pytest.mark.ac("E42-AC-01", "E42-AC-02")\n'
        "@pytest.mark.slow\n"
        "def test_add_and_count() -> None:\n"
        "    pass\n"
    )
    acs = trace(source)
    assert acs["AC-01"] == ["test_add_and_count"]
    assert acs["AC-02"] == ["test_add_and_count"]


@pytest.mark.ac("E31-AC-02")
def test_ac_mark_on_an_async_test_and_a_class_method() -> None:
    source = (
        "import pytest\n"
        "\n"
        "\n"
        "class TestWidgets:\n"
        '    @pytest.mark.ac("E42-AC-03")\n'
        "    def test_remove(self) -> None:\n"
        "        pass\n"
        "\n"
        "\n"
        '@pytest.mark.ac("E42-AC-04")\n'
        "async def test_rename() -> None:\n"
        "    pass\n"
    )
    acs = trace(source)
    assert acs["AC-03"] == ["test_remove"]
    assert acs["AC-04"] == ["test_rename"]


@pytest.mark.ac("E31-AC-02")
def test_tag_in_another_marks_string_is_not_a_marker() -> None:
    source = (
        "import pytest\n"
        "\n"
        "\n"
        '@pytest.mark.skip(reason="see E42-AC-01")\n'
        "def test_skipped() -> None:\n"
        "    pass\n"
    )
    assert trace(source).get("AC-01", []) == []


@pytest.mark.ac("E31-AC-03")
def test_tag_in_a_comment_binds_to_the_next_test() -> None:
    source = (
        "# E42-AC-01\n"
        "def test_add() -> None:\n"
        "    pass\n"
        "\n"
        "\n"
        "def test_count() -> None:\n"
        "    pass  # covers E42-AC-02\n"
        "\n"
        "\n"
        "def test_remove() -> None:\n"
        "    pass\n"
    )
    acs = trace(source)
    assert acs["AC-01"] == ["test_add"]
    assert acs["AC-02"] == ["test_remove"]


@pytest.mark.ac("E31-AC-03")
def test_tag_in_a_comment_with_no_test_after_it_is_listed_under_the_file() -> None:
    source = "def test_add() -> None:\n    pass\n\n\n# E42-AC-01\n"
    traced = evidence.trace_file(PATH, source, EPIC)
    assert traced.acs == {"AC-01": []}
    assert traced.tests == 1


@pytest.mark.ac("E31-AC-05")
def test_tag_in_a_test_docstring_binds_to_that_test() -> None:
    source = (
        "def test_add() -> None:\n"
        '    """Widgets can be added (E42-AC-01)."""\n'
        "\n"
        "\n"
        "def test_count() -> None:\n"
        "    '''\n"
        "    E42-AC-02: widgets can be counted.\n"
        "    '''\n"
    )
    acs = trace(source)
    assert acs["AC-01"] == ["test_add"]
    assert acs["AC-02"] == ["test_count"]


@pytest.mark.ac("E31-AC-05")
def test_a_later_string_in_a_test_is_not_its_docstring() -> None:
    source = (
        "def test_add() -> None:\n"
        '    """Widgets can be added."""\n'
        '    note = "E42-AC-01"\n'
        "    assert note\n"
    )
    assert trace(source).get("AC-01", []) == []


@pytest.mark.ac("E31-AC-06")
def test_comment_marker_inside_a_string_is_a_string() -> None:
    source = (
        'HEADER = "# E42-AC-01"\n'
        "LINES = '''\n"
        "# E42-AC-02\n"
        "'''\n"
        "\n"
        "\n"
        "def test_header() -> None:\n"
        "    assert HEADER\n"
    )
    acs = trace(source)
    assert acs.get("AC-01", []) == []
    assert acs.get("AC-02", []) == []


@pytest.mark.ac("E31-AC-06")
def test_mark_text_inside_a_string_is_a_string() -> None:
    source = (
        "PY_TESTS = '''\n"
        '@pytest.mark.ac("E42-AC-01")\n'
        "def test_inner() -> None:\n"
        "    pass\n"
        "'''\n"
        "\n"
        "\n"
        "def test_outer() -> None:\n"
        "    assert PY_TESTS\n"
    )
    traced = evidence.trace_file(PATH, source, EPIC)
    assert traced.acs.get("AC-01", []) == []
    assert traced.tests == 1


E08_T5_COMMIT = "2974090"
E08_T5_FILES = ["tests/test_evidence_skill.py", "tests/test_evidence_done_when.py"]


def _at_commit(path: str) -> str:
    return subprocess.run(
        ["git", "show", f"{E08_T5_COMMIT}:{path}"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    ).stdout


@pytest.mark.ac("E31-AC-07")
@pytest.mark.parametrize("path", E08_T5_FILES)
def test_e08_t5_files_do_not_trace_ac_17_or_19_to_the_stdlib_test(path: str) -> None:
    acs = evidence.trace_file(path, _at_commit(path), "E08").acs
    for ac in ("AC-17", "AC-19"):
        assert "test_evidence_py_is_standard_library_only" not in acs.get(ac, [])


@pytest.mark.ac("E31-AC-07")
def test_e08_t5_files_still_trace_their_real_marks() -> None:
    acs = evidence.trace_file(E08_T5_FILES[0], _at_commit(E08_T5_FILES[0]), "E08").acs
    assert "test_evidence_py_is_standard_library_only" in acs["AC-20"]


@pytest.mark.ac("E31-AC-08")
def test_e08_t2_tests_are_relocked_with_the_product_owners_approval() -> None:
    record = tomllib.loads(
        (REPO_ROOT / ".agentic" / "locks" / "E08-T2.toml").read_text(encoding="utf-8")
    )
    assert [f["path"] for f in record["files"]] == ["tests/test_evidence_draft.py"]
    approved = record.get("approved_by")
    assert isinstance(approved, str) and approved.strip(), "relock carries no approval"
    assert record["locked"].date().isoformat() >= "2026-11-24", "E08-T2 has not been relocked"
    checked = subprocess.run(
        ["python", ".factory/agents/agents.py", "check"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert checked.returncode == 0, checked.stdout + checked.stderr
