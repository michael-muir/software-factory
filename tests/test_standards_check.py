"""E11/T1: the pack format, `standards.py check`, the `[standards]` config, the house seed, and
running the validator in the gate and `install.py check`.

Covers E11 AC-01 to AC-04 and AC-09 to AC-11. Expectations come from the E11 spec, the design
note (`docs/design/E11-standards-design.md`) and ADRs 0033 and 0036, not from the implementation.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

import standards
import state
from factory_installer import cli, config_schema
from factory_installer.kit import SEED_FILES, load_kit
from tests._ac import REPO_ROOT
from tests._gate import PASS, gate_repo, profile, run_gate, touches
from tests._kits import make_kit
from tests._repo import git_repo
from tests._standards import (
    HEADER,
    SEPARATOR,
    front,
    pack,
    pack_rel,
    row_line,
    rows,
    write_packs,
)

KIT = REPO_ROOT / "kit"
STANDARDS_PY = KIT / ".factory" / "standards" / "standards.py"
HOUSE = ".factory/standards/house/rules.md"
CONFIG = ".agentic/config.toml"
KIT_CONFIG = KIT / CONFIG
ALPHA = pack_rel("alpha")


def problems(root: Path) -> list[str]:
    return [str(p) for p in standards.validate(root)]


def at(root: Path, rel: str, where: str) -> list[str]:
    return [p for p in problems(root) if p.startswith(f"{rel}: {where}: ")]


def line_of(text: str, needle: str) -> int:
    """The 1-based line number of the first line containing `needle`."""
    for number, line in enumerate(text.splitlines(), start=1):
        if needle in line:
            return number
    raise AssertionError(f"{needle!r} not in text")


def alpha(tmp_path: Path, text: str) -> Path:
    return write_packs(tmp_path, {"alpha": text})


# --- AC-01: the front matter -------------------------------------------------------------------


@pytest.mark.ac("E11-AC-01")
def test_a_minimal_pack_is_valid(tmp_path: Path) -> None:
    assert problems(alpha(tmp_path, pack())) == []


@pytest.mark.ac("E11-AC-01")
def test_the_reader_returns_the_front_matter_and_the_rules(tmp_path: Path) -> None:
    extra = 'detect = ["*.uproject"]\nreplaces = ["beta"]'
    path = alpha(tmp_path, pack(extra=extra)) / ALPHA
    read, found = standards.read_pack(path, ALPHA)
    assert found == []
    assert read is not None
    assert (read.name, read.title, read.prefix) == ("alpha", "Alpha pack", "AL")
    assert read.applies_to == ["*.py"]
    assert read.detect == ["*.uproject"]
    assert read.replaces == ["beta"]
    assert [(s.title, s.url, s.licence) for s in read.sources] == [
        ("Alpha guide", "https://example.com/alpha/", "CC-BY-4.0")
    ]
    assert [r.id for r in read.rules] == ["AL-001", "AL-002", "AL-003"]
    first = read.rules[0]
    assert (first.severity, first.text, first.why) == (
        "blocker",
        "Never swallow an error.",
        "Hidden failures.",
    )
    assert first.source == "https://example.com/alpha/#1"


@pytest.mark.ac("E11-AC-01")
def test_detect_and_replaces_default_to_empty(tmp_path: Path) -> None:
    read, _ = standards.read_pack(alpha(tmp_path, pack()) / ALPHA, ALPHA)
    assert read is not None
    assert (read.detect, read.replaces) == ([], [])


@pytest.mark.ac("E11-AC-01")
def test_the_name_must_match_the_folder(tmp_path: Path) -> None:
    root = write_packs(tmp_path, {"alpha": pack(name="other")})
    assert at(root, ALPHA, "front matter: name"), problems(root)


@pytest.mark.ac("E11-AC-01")
@pytest.mark.parametrize("key", ["name", "title", "prefix", "applies_to", "sources"])
def test_each_required_key_is_required(tmp_path: Path, key: str) -> None:
    root = alpha(tmp_path, pack(front_text=front(omit=[key])))
    assert at(root, ALPHA, f"front matter: {key}"), problems(root)


@pytest.mark.ac("E11-AC-01")
@pytest.mark.parametrize("prefix", ["A", "ABCDEF", "al", "A1", "A-B", ""])
def test_the_prefix_is_two_to_five_capital_letters(tmp_path: Path, prefix: str) -> None:
    text = pack(front_text=front(prefix=prefix), table=rows("AL"))
    root = alpha(tmp_path, text)
    assert at(root, ALPHA, "front matter: prefix"), problems(root)


@pytest.mark.ac("E11-AC-01")
@pytest.mark.parametrize("prefix", ["AB", "ABCDE"])
def test_prefixes_of_two_and_five_letters_are_valid(tmp_path: Path, prefix: str) -> None:
    root = alpha(tmp_path, pack(prefix=prefix))
    assert problems(root) == []


@pytest.mark.ac("E11-AC-01")
@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("title", '""'),
        ("title", "3"),
        ("applies_to", "[]"),
        ("applies_to", '"*.py"'),
        ("applies_to", '["*.py", ""]'),
        ("applies_to", "[1]"),
    ],
)
def test_bad_titles_and_globs_are_reported(tmp_path: Path, key: str, value: str) -> None:
    text = front(omit=[key], extra=f"{key} = {value}")
    root = alpha(tmp_path, pack(front_text=text))
    assert at(root, ALPHA, f"front matter: {key}"), problems(root)


@pytest.mark.ac("E11-AC-01")
@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("detect", '"*.uproject"'),
        ("detect", '[""]'),
        ("detect", "[1]"),
        ("replaces", '"cpp"'),
        ("replaces", "[2]"),
    ],
)
def test_bad_detect_and_replaces_are_reported(tmp_path: Path, key: str, value: str) -> None:
    root = alpha(tmp_path, pack(extra=f"{key} = {value}"))
    assert at(root, ALPHA, f"front matter: {key}"), problems(root)


@pytest.mark.ac("E11-AC-01")
@pytest.mark.parametrize(
    "sources",
    [
        (),
        (("Alpha guide", "http://example.com/alpha/", "CC-BY-4.0"),),
        (("Alpha guide", "example.com/alpha/", "CC-BY-4.0"),),
        (("", "https://example.com/alpha/", "CC-BY-4.0"),),
        (("Alpha guide", "https://example.com/alpha/", ""),),
    ],
)
def test_sources_need_a_title_an_https_url_and_a_licence(
    tmp_path: Path, sources: tuple[tuple[str, str, str], ...]
) -> None:
    text = pack(front_text=front(sources=sources))
    root = alpha(tmp_path, text)
    assert at(root, ALPHA, "front matter: sources"), problems(root)


@pytest.mark.ac("E11-AC-01")
def test_a_source_missing_its_licence_key_is_reported(tmp_path: Path) -> None:
    text = front(
        omit=["sources"], extra='[[sources]]\ntitle = "A"\nurl = "https://example.com/alpha/"'
    )
    root = alpha(tmp_path, pack(front_text=text))
    assert at(root, ALPHA, "front matter: sources"), problems(root)


@pytest.mark.ac("E11-AC-01")
def test_an_unknown_front_matter_key_is_reported(tmp_path: Path) -> None:
    root = alpha(tmp_path, pack(extra='colour = "blue"'))
    assert at(root, ALPHA, "front matter: colour"), problems(root)


@pytest.mark.ac("E11-AC-01")
@pytest.mark.parametrize(
    "text",
    [
        "# No front matter\n",
        '+++\nname = "alpha"\n',
        "+++\nname = = broken\n+++\n\n# Alpha pack\n",
        '\n+++\nname = "alpha"\n+++\n',
    ],
)
def test_missing_unclosed_or_invalid_front_matter_is_a_problem(tmp_path: Path, text: str) -> None:
    root = alpha(tmp_path, text)
    assert at(root, ALPHA, "front matter"), problems(root)


@pytest.mark.ac("E11-AC-01")
def test_prefixes_are_unique_among_installed_packs(tmp_path: Path) -> None:
    root = write_packs(tmp_path, {"alpha": pack(), "beta": pack("beta", title="Beta pack")})
    found = at(root, pack_rel("beta"), "front matter: prefix")
    assert found, problems(root)
    assert "alpha" in found[0]


@pytest.mark.ac("E11-AC-01")
def test_replaces_must_name_installed_packs(tmp_path: Path) -> None:
    root = alpha(tmp_path, pack(extra='replaces = ["nothing"]'))
    assert at(root, ALPHA, "front matter: replaces"), problems(root)


@pytest.mark.ac("E11-AC-01")
def test_a_pack_cannot_replace_itself(tmp_path: Path) -> None:
    root = alpha(tmp_path, pack(extra='replaces = ["alpha"]'))
    assert at(root, ALPHA, "front matter: replaces"), problems(root)


@pytest.mark.ac("E11-AC-01")
def test_replaces_cycles_are_reported(tmp_path: Path) -> None:
    beta = pack(
        "beta", title="Beta pack", prefix="BE", extra='replaces = ["alpha"]', table=rows("BE")
    )
    root = write_packs(tmp_path, {"alpha": pack(extra='replaces = ["beta"]'), "beta": beta})
    assert at(root, ALPHA, "front matter: replaces") or at(
        root, pack_rel("beta"), "front matter: replaces"
    ), problems(root)


@pytest.mark.ac("E11-AC-01")
def test_a_valid_replaces_and_detect_pair_is_accepted(tmp_path: Path) -> None:
    beta = pack("beta", title="Beta pack", prefix="BE", table=rows("BE"))
    root = write_packs(
        tmp_path,
        {"alpha": pack(extra='detect = ["*.uproject"]\nreplaces = ["beta"]'), "beta": beta},
    )
    assert problems(root) == []


@pytest.mark.ac("E11-AC-01")
@pytest.mark.parametrize(
    "text",
    [
        "+++\nname = 1\n+++\nbody\n",
        "+++\r\nname = 1\r\n+++\r\n",
        "+++\n+++\n",
        "+++ \nname = 1\n+++\n",
        "\n+++\nname = 1\n+++\n",
        "+++\nname = 1\n",
        "",
    ],
)
def test_front_matter_is_split_as_state_py_splits_it(text: str) -> None:
    """ADR 0033: standards.py's own front matter reader reads `+++` blocks as state.py does."""
    assert standards.split(text) == state.split(text)


# --- AC-02: the body -----------------------------------------------------------------------------


@pytest.mark.ac("E11-AC-02")
@pytest.mark.parametrize("heading", ["Another title", ""])
def test_the_first_heading_is_the_title(tmp_path: Path, heading: str) -> None:
    root = alpha(tmp_path, pack(heading=heading))
    assert at(root, ALPHA, "body"), problems(root)


@pytest.mark.ac("E11-AC-02")
def test_the_left_to_the_tools_section_is_required(tmp_path: Path) -> None:
    root = alpha(tmp_path, pack(left=None))
    found = at(root, ALPHA, "body")
    assert found, problems(root)
    assert "Left to the tools" in found[0]


@pytest.mark.ac("E11-AC-02")
@pytest.mark.parametrize(
    "left", ["\n", "The formatter handles layout.\n", "The linter handles imports.\n"]
)
def test_the_left_to_the_tools_section_names_the_format_and_lint_checks(
    tmp_path: Path, left: str
) -> None:
    root = alpha(tmp_path, pack(left=left))
    found = at(root, ALPHA, "body")
    assert found, problems(root)
    assert "Left to the tools" in found[0]


@pytest.mark.ac("E11-AC-02")
def test_the_rules_section_is_required(tmp_path: Path) -> None:
    text = pack().replace("## Rules", "## Other")
    root = alpha(tmp_path, text)
    found = at(root, ALPHA, "body")
    assert found, problems(root)
    assert "Rules" in found[0]


@pytest.mark.ac("E11-AC-02")
@pytest.mark.parametrize(
    "header",
    [
        "| Id | Severity | Rule | Why/example | Source |",
        "| Rule id | Severity | Rule | Source |",
        "| Rule id | Severity | Rule | Why/example | Source | Notes |",
        "| rule id | severity | rule | why/example | source |",
    ],
)
def test_the_table_header_is_exact(tmp_path: Path, header: str) -> None:
    text = pack(header=header)
    root = alpha(tmp_path, text)
    assert at(root, ALPHA, f"line {line_of(text, header)}"), problems(root)


@pytest.mark.ac("E11-AC-02")
def test_the_rules_section_holds_one_table_only(tmp_path: Path) -> None:
    second = "\nMore rules:\n\n" + "\n".join([HEADER, SEPARATOR, row_line(rows()[0])]) + "\n"
    text = pack(table=rows()[1:], after_table=second)
    root = alpha(tmp_path, text)
    assert at(root, ALPHA, f"line {line_of(text, 'More rules:') + 2}"), problems(root)


@pytest.mark.ac("E11-AC-02")
def test_the_table_needs_its_separator_line(tmp_path: Path) -> None:
    text = pack().replace(SEPARATOR + "\n", "")
    root = alpha(tmp_path, text)
    assert problems(root), "a table without a separator line was accepted"


@pytest.mark.ac("E11-AC-02")
def test_an_empty_rules_table_is_valid_in_shape(tmp_path: Path) -> None:
    root = alpha(tmp_path, pack(table=[]))
    assert problems(root) == []


# --- AC-03: the rows ------------------------------------------------------------------------------


def _row_problem(tmp_path: Path, bad: tuple[str, str, str, str, str], position: int = 1) -> None:
    table = rows()
    table[position] = bad
    text = pack(table=table)
    root = alpha(tmp_path, text)
    where = f"line {line_of(text, row_line(bad))}"
    assert at(root, ALPHA, where), problems(root)


GOOD_SOURCE = "[s](https://example.com/alpha/#x)"


@pytest.mark.ac("E11-AC-03")
@pytest.mark.parametrize("rule_id", ["BE-002", "AL-02", "AL-0002", "al-002", "AL002", ""])
def test_a_row_id_uses_the_packs_prefix_and_three_digits(tmp_path: Path, rule_id: str) -> None:
    _row_problem(tmp_path, (rule_id, "major", "A rule.", "Why.", GOOD_SOURCE))


@pytest.mark.ac("E11-AC-03")
def test_a_duplicate_id_is_reported(tmp_path: Path) -> None:
    _row_problem(tmp_path, ("AL-001", "major", "Again.", "Why.", GOOD_SOURCE))


@pytest.mark.ac("E11-AC-03")
def test_ids_are_in_ascending_order(tmp_path: Path) -> None:
    table = rows()
    table[1], table[2] = table[2], table[1]
    text = pack(table=table)
    root = alpha(tmp_path, text)
    assert at(root, ALPHA, f"line {line_of(text, row_line(table[2]))}"), problems(root)


@pytest.mark.ac("E11-AC-03")
def test_gaps_in_the_numbering_are_allowed(tmp_path: Path) -> None:
    table = rows()
    table[2] = ("AL-007", *table[2][1:])
    assert problems(alpha(tmp_path, pack(table=table))) == []


@pytest.mark.ac("E11-AC-03")
@pytest.mark.parametrize("severity", ["critical", "Major", "", "low"])
def test_the_severity_is_one_of_four(tmp_path: Path, severity: str) -> None:
    _row_problem(tmp_path, ("AL-002", severity, "A rule.", "Why.", GOOD_SOURCE))


@pytest.mark.ac("E11-AC-03")
@pytest.mark.parametrize("severity", ["blocker", "major", "minor", "retired"])
def test_each_of_the_four_severities_is_valid(tmp_path: Path, severity: str) -> None:
    table = rows()
    table[1] = ("AL-002", severity, "A rule.", "Why.", GOOD_SOURCE)
    assert problems(alpha(tmp_path, pack(table=table))) == []


@pytest.mark.ac("E11-AC-03")
@pytest.mark.parametrize("cells", [("", "Why."), ("A rule.", ""), ("  ", "Why.")])
def test_the_rule_and_why_cells_are_not_empty(tmp_path: Path, cells: tuple[str, str]) -> None:
    _row_problem(tmp_path, ("AL-002", "major", cells[0], cells[1], GOOD_SOURCE))


@pytest.mark.ac("E11-AC-03")
@pytest.mark.parametrize(
    "source",
    [
        "https://example.com/alpha/#x",
        "PEP 8",
        "[s](https://elsewhere.example.org/alpha/)",
        "[s](https://example.com/alphabet/)",
        "[s](http://example.com/alpha/#x)",
        "[a](https://example.com/alpha/#1) [b](https://example.com/alpha/#2)",
        "",
    ],
)
def test_the_source_is_one_link_under_a_named_source(tmp_path: Path, source: str) -> None:
    _row_problem(tmp_path, ("AL-002", "major", "A rule.", "Why.", source))


@pytest.mark.ac("E11-AC-03")
def test_a_source_may_link_to_any_of_the_named_sources(tmp_path: Path) -> None:
    sources = (
        ("Alpha guide", "https://example.com/alpha/", "CC-BY-4.0"),
        ("Second guide", "https://second.example.org/guide", "MIT"),
    )
    table = rows()
    table[1] = ("AL-002", "major", "A rule.", "Why.", "[g](https://second.example.org/guide#n)")
    text = pack(front_text=front(sources=sources), table=table)
    assert problems(alpha(tmp_path, text)) == []


@pytest.mark.ac("E11-AC-03")
@pytest.mark.parametrize(
    "line",
    [
        "| AL-002 | major | A rule. | Why. |",
        "| AL-002 | major | A rule. | Why. | [s](https://example.com/alpha/#x) | extra |",
    ],
)
def test_a_row_with_the_wrong_number_of_cells_is_reported(tmp_path: Path, line: str) -> None:
    text = pack(table=rows()[:1]).rstrip("\n") + "\n" + line + "\n"
    root = alpha(tmp_path, text)
    assert at(root, ALPHA, f"line {line_of(text, line)}"), problems(root)


@pytest.mark.ac("E11-AC-03")
def test_an_escaped_pipe_is_part_of_the_cell(tmp_path: Path) -> None:
    table = rows()
    table[1] = ("AL-002", "major", r"Use `a \| b` for unions.", "Why.", GOOD_SOURCE)
    path = alpha(tmp_path, pack(table=table)) / ALPHA
    read, found = standards.read_pack(path, ALPHA)
    assert found == []
    assert read is not None
    assert read.rules[1].text == "Use `a | b` for unions."


@pytest.mark.ac("E11-AC-03")
def test_a_retired_rule_keeps_its_id(tmp_path: Path) -> None:
    table = rows()
    table[0] = ("AL-001", "retired", "Old rule.", "Replaced by AL-003.", table[0][4])
    path = alpha(tmp_path, pack(table=table)) / ALPHA
    read, found = standards.read_pack(path, ALPHA)
    assert found == []
    assert read is not None
    assert (read.rules[0].id, read.rules[0].severity) == ("AL-001", "retired")


# --- AC-04: standards.py check ----------------------------------------------------------------


@pytest.mark.ac("E11-AC-04")
def test_check_exits_0_on_clean_packs(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = alpha(tmp_path, pack())
    assert standards.main(["--root", str(root), "check"]) == 0, capsys.readouterr()


@pytest.mark.ac("E11-AC-04")
def test_check_exits_1_and_lists_each_problem(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = write_packs(
        tmp_path, {"alpha": pack(name="wrong"), "beta": pack("beta", title="Beta", left=None)}
    )
    assert standards.main(["--root", str(root), "check"]) == 1
    out = capsys.readouterr().out
    assert f"{ALPHA}: front matter: name: " in out
    assert f"{pack_rel('beta')}: body: " in out


@pytest.mark.ac("E11-AC-04")
def test_a_repo_without_packs_has_no_problems(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert problems(tmp_path) == []
    assert standards.main(["--root", str(tmp_path), "check"]) == 0, capsys.readouterr()


@pytest.mark.ac("E11-AC-04")
def test_problems_are_sorted_by_file_then_line(tmp_path: Path) -> None:
    bad = rows()
    bad[1] = ("AL-002", "nope", "A rule.", "Why.", GOOD_SOURCE)
    bad[2] = ("AL-003", "nope", "A rule.", "Why.", GOOD_SOURCE)
    root = write_packs(
        tmp_path,
        {
            "beta": pack("beta", title="B", prefix="BE", left=None, table=rows("BE")),
            "alpha": pack(table=bad),
        },
    )
    found = problems(root)
    assert found == sorted(found, key=lambda p: (p.split(": ")[0], _line_key(p))), found
    assert found[0].startswith(ALPHA), found


def _line_key(problem: str) -> int:
    where = problem.split(": ")[1]
    return int(where.split()[1]) if where.startswith("line ") else 0


@pytest.mark.ac("E11-AC-04")
@pytest.mark.parametrize(
    "text",
    [
        "",
        "+++",
        "+++\n+++",
        "+++\n+++\n",
        "﻿+++\nname = 1\n+++\n",
        "+++\nsources = 3\n+++\n## Rules\n|",
        "+++\nsources = [1, 2]\n+++\n## Rules\n| a |\n| --- |\n|",
        "+++\napplies_to = [[]]\n+++\n## Rules\n" + HEADER + "\n" + SEPARATOR + "\n| | | | | |\n",
        "\x00\x01binary",
    ],
)
def test_the_reader_never_raises_on_bad_input(tmp_path: Path, text: str) -> None:
    root = alpha(tmp_path, text)
    read, found = standards.read_pack(root / ALPHA, ALPHA)
    assert read is None or isinstance(read, standards.Pack)
    assert found, "bad input produced no problem"
    assert problems(root)


@pytest.mark.ac("E11-AC-04")
def test_a_rules_md_that_is_not_utf8_is_a_problem_not_a_crash(tmp_path: Path) -> None:
    path = tmp_path / ALPHA
    path.parent.mkdir(parents=True)
    path.write_bytes(b'+++\nname = "\xff"\n+++\n')
    assert at(tmp_path, ALPHA, "front matter"), problems(tmp_path)


@pytest.mark.ac("E11-AC-04")
def test_the_cli_runs_as_a_script(tmp_path: Path) -> None:
    root = write_packs(tmp_path, {"alpha": pack(name="wrong")})
    result = subprocess.run(
        [sys.executable, str(STANDARDS_PY), "check"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1, result.stdout + result.stderr
    assert f"{ALPHA}: front matter: name: " in result.stdout


@pytest.mark.ac("E11-AC-04")
def test_the_problem_format_is_file_where_problem(tmp_path: Path) -> None:
    root = alpha(tmp_path, pack(name="wrong"))
    found = standards.validate(root)
    assert found
    first = found[0]
    assert str(first) == f"{first.path}: {first.where}: {first.message}"
    assert first.path == ALPHA


# --- AC-09: the [standards] config -------------------------------------------------------------


def _config(packs: str = "{}", ignore: str = "[]") -> str:
    return f"schema_version = 1\n\n[standards]\npacks = {packs}\nignore = {ignore}\n"


@pytest.mark.ac("E11-AC-09")
def test_the_standards_section_defaults_are_the_specs() -> None:
    fields = config_schema.SECTIONS["standards"]
    assert set(fields) == {"packs", "ignore"}
    assert fields["packs"].default == {}
    assert fields["ignore"].default == []


@pytest.mark.ac("E11-AC-09")
def test_the_kit_config_has_the_standards_defaults() -> None:
    with KIT_CONFIG.open("rb") as f:
        data = tomllib.load(f)
    assert data["standards"] == {"packs": {}, "ignore": []}
    assert config_schema.render_default() == KIT_CONFIG.read_text(encoding="utf-8")


@pytest.mark.ac("E11-AC-09")
@pytest.mark.parametrize(
    ("packs", "ignore"),
    [("{}", "[]"), ("{ python = true, cpp = false }", '["PY-001", "UE-010"]')],
)
def test_valid_standards_values_pass_the_schema(packs: str, ignore: str) -> None:
    result = config_schema.validate(tomllib.loads(_config(packs, ignore)))
    assert [i for i in result.errors if i.key.startswith("standards")] == []


@pytest.mark.ac("E11-AC-09")
@pytest.mark.parametrize(
    ("text", "key"),
    [
        (_config(packs='"python"'), "standards.packs"),
        (_config(packs='{ python = "yes" }'), "standards.packs"),
        (_config(packs="{ python = 1 }"), "standards.packs"),
        (_config(ignore='"PY-001"'), "standards.ignore"),
        (_config(ignore='["py-001"]'), "standards.ignore"),
        (_config(ignore='["PY-1"]'), "standards.ignore"),
        (_config(ignore='["ABCDEF-001"]'), "standards.ignore"),
        (_config() + "colour = 1\n", "standards.colour"),
    ],
)
def test_bad_standards_values_fail_the_schema(text: str, key: str) -> None:
    result = config_schema.validate(tomllib.loads(text))
    assert key in [i.key for i in result.errors], result.errors


@pytest.mark.ac("E11-AC-09")
def test_an_unknown_pack_name_is_a_problem(tmp_path: Path) -> None:
    root = write_packs(tmp_path, {"alpha": pack()}, config=_config(packs="{ nothing = false }"))
    found = at(root, CONFIG, "config: standards.packs")
    assert found, problems(root)
    assert "nothing" in found[0]


@pytest.mark.ac("E11-AC-09")
def test_an_unknown_ignored_rule_is_a_problem(tmp_path: Path) -> None:
    root = write_packs(tmp_path, {"alpha": pack()}, config=_config(ignore='["AL-009"]'))
    found = at(root, CONFIG, "config: standards.ignore")
    assert found, problems(root)
    assert "AL-009" in found[0]


@pytest.mark.ac("E11-AC-09")
def test_known_names_and_ids_are_accepted(tmp_path: Path) -> None:
    config = _config(packs="{ alpha = false }", ignore='["AL-002"]')
    root = write_packs(tmp_path, {"alpha": pack()}, config=config)
    assert problems(root) == []


@pytest.mark.ac("E11-AC-09")
@pytest.mark.parametrize(
    "config",
    [
        "schema_version = 1\n",
        "schema_version = 1\n\n[standards]\n",
        "schema_version = 1\n\n[standards]\npacks = { alpha = true }\n",
    ],
)
def test_a_config_without_the_table_or_its_keys_uses_the_defaults(
    tmp_path: Path, config: str
) -> None:
    root = write_packs(tmp_path, {"alpha": pack()}, config=config)
    assert problems(root) == []


@pytest.mark.ac("E11-AC-09")
def test_bad_types_in_the_config_are_problems_not_crashes(tmp_path: Path) -> None:
    config = 'schema_version = 1\n\n[standards]\npacks = "alpha"\nignore = 3\n'
    root = write_packs(tmp_path, {"alpha": pack()}, config=config)
    assert at(root, CONFIG, "config: standards.packs"), problems(root)
    assert at(root, CONFIG, "config: standards.ignore"), problems(root)


@pytest.mark.ac("E11-AC-09")
def test_install_check_reports_an_unknown_pack_name(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = write_packs(tmp_path, {"alpha": pack()})
    config = KIT_CONFIG.read_text(encoding="utf-8").replace(
        "packs = {}", "packs = { nothing = true }"
    )
    (root / CONFIG).parent.mkdir(parents=True, exist_ok=True)
    (root / CONFIG).write_text(config, encoding="utf-8")
    assert cli.main(["check", str(root)]) == 1
    out = capsys.readouterr()
    assert f"{CONFIG}: config: standards.packs: " in out.out + out.err


@pytest.mark.ac("E11-AC-09")
def test_install_check_passes_a_config_without_the_standards_table(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = git_repo(tmp_path / "repo")
    assert cli.main([str(repo)]) == 0
    capsys.readouterr()
    config = repo / CONFIG
    text = config.read_text(encoding="utf-8")
    start = text.index("[standards]")
    end = text.find("\n[", start + 1)
    config.write_text(text[:start] + (text[end + 1 :] if end != -1 else ""), encoding="utf-8")
    assert "[standards]" not in config.read_text(encoding="utf-8")
    code = cli.main(["check", str(repo)])
    out = capsys.readouterr()
    assert code == 0, out.out + out.err
    assert "standards.packs: not set, using default {}" in out.out


# --- AC-10: the house pack ---------------------------------------------------------------------


@pytest.mark.ac("E11-AC-10")
def test_the_house_pack_is_a_seed_file_not_a_kit_file() -> None:
    assert HOUSE in SEED_FILES
    kit = load_kit()
    assert HOUSE in kit.files
    assert not kit.is_kit_managed(HOUSE)


@pytest.mark.ac("E11-AC-10")
def test_the_house_template_is_a_valid_pack_with_one_retired_example(tmp_path: Path) -> None:
    template = (KIT / HOUSE).read_text(encoding="utf-8")
    root = write_packs(tmp_path, {"house": template})
    assert problems(root) == []
    read, _ = standards.read_pack(root / HOUSE, HOUSE)
    assert read is not None
    assert (read.name, read.prefix) == ("house", "HOUSE")
    assert [(r.id, r.severity) for r in read.rules] == [("HOUSE-001", "retired")]


def _install(repo: Path, capsys: pytest.CaptureFixture[str], *extra: str) -> dict[str, object]:
    code = cli.main([str(repo), "--json", *extra])
    out = capsys.readouterr().out
    assert code == 0, out
    report = json.loads(out)
    assert isinstance(report, dict)
    return report


def _manifest(repo: Path) -> dict[str, object]:
    data = json.loads((repo / ".factory" / "manifest.json").read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


@pytest.mark.ac("E11-AC-10")
def test_install_creates_the_house_pack_outside_the_manifest(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = git_repo(tmp_path / "repo")
    _install(repo, capsys)
    assert (repo / HOUSE).read_bytes() == (KIT / HOUSE).read_bytes()
    files = _manifest(repo)["files"]
    assert isinstance(files, dict)
    assert HOUSE not in files
    deleted = _manifest(repo).get("deleted", [])
    assert isinstance(deleted, list)
    assert HOUSE not in deleted


@pytest.mark.ac("E11-AC-10")
def test_reinstall_and_upgrade_never_overwrite_the_house_pack(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = git_repo(tmp_path / "repo")
    _install(repo, capsys)
    ours = (KIT / HOUSE).read_text(encoding="utf-8") + "\nOur own notes.\n"
    (repo / HOUSE).write_text(ours, encoding="utf-8")
    _install(repo, capsys)
    assert (repo / HOUSE).read_text(encoding="utf-8") == ours
    v2 = make_kit(tmp_path, "0.9.0", {HOUSE: b"+++\nchanged template\n+++\n"})
    _install(repo, capsys, "--kit", str(v2))
    assert (repo / HOUSE).read_text(encoding="utf-8") == ours
    _install(repo, capsys, "--kit", str(v2), "--force")
    assert (repo / HOUSE).read_text(encoding="utf-8") == ours
    assert not (repo / (HOUSE + ".factory-new")).exists()
    files = _manifest(repo)["files"]
    assert isinstance(files, dict)
    assert HOUSE not in files


@pytest.mark.ac("E11-AC-10")
def test_an_upgrade_that_drops_the_template_keeps_the_house_pack(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = git_repo(tmp_path / "repo")
    _install(repo, capsys)
    v2 = make_kit(tmp_path, "0.9.0", {HOUSE: None})
    _install(repo, capsys, "--kit", str(v2))
    assert (repo / HOUSE).read_bytes() == (KIT / HOUSE).read_bytes()


@pytest.mark.ac("E11-AC-10")
def test_a_deleted_house_pack_comes_back_from_the_template(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = git_repo(tmp_path / "repo")
    _install(repo, capsys)
    (repo / HOUSE).unlink()
    report = _install(repo, capsys)
    assert (repo / HOUSE).read_bytes() == (KIT / HOUSE).read_bytes()
    files = report["files"]
    assert isinstance(files, dict)
    assert HOUSE in files["created"]


@pytest.mark.ac("E11-AC-10")
def test_a_manifest_that_claims_the_house_pack_cannot_remove_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = git_repo(tmp_path / "repo")
    _install(repo, capsys)
    path = repo / ".factory" / "manifest.json"
    data = _manifest(repo)
    files = data["files"]
    assert isinstance(files, dict)
    files[HOUSE] = "0" * 64
    path.write_text(json.dumps(data), encoding="utf-8")
    v2 = make_kit(tmp_path, "0.9.0", {HOUSE: None})
    _install(repo, capsys, "--kit", str(v2))
    assert (repo / HOUSE).is_file()


@pytest.mark.ac("E11-AC-10")
def test_a_fresh_install_passes_install_check(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = git_repo(tmp_path / "repo")
    _install(repo, capsys)
    code = cli.main(["check", str(repo)])
    out = capsys.readouterr()
    assert code == 0, out.out + out.err


# --- AC-11: the gate and install.py check ------------------------------------------------------


def _gated(tmp_path: Path, packs: dict[str, str], *, with_module: bool = True) -> Path:
    repo = gate_repo(
        tmp_path / "repo",
        {
            "py.toml": profile(
                "py", ["marker.txt"], {"format": touches("ran-format.txt"), "lint": PASS}
            )
        },
        files={"marker.txt": "x\n"},
    )
    write_packs(repo, packs)
    if with_module:
        target = repo / ".factory" / "standards" / "standards.py"
        shutil.copyfile(STANDARDS_PY, target)
    return repo


@pytest.mark.ac("E11-AC-11")
def test_the_gate_exits_2_on_an_invalid_pack_and_runs_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _gated(tmp_path, {"alpha": pack(name="wrong")})
    code, output = run_gate(repo, monkeypatch, capsys)
    assert code == 2, output
    assert f"{ALPHA}: front matter: name: " in output
    assert "standards.py check" in output
    assert not (repo / "ran-format.txt").exists()


@pytest.mark.ac("E11-AC-11")
def test_the_gate_exits_2_on_a_bad_standards_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _gated(tmp_path, {"alpha": pack()})
    (repo / CONFIG).parent.mkdir(parents=True, exist_ok=True)
    (repo / CONFIG).write_text(_config(ignore='["AL-404"]'), encoding="utf-8")
    code, output = run_gate(repo, monkeypatch, capsys)
    assert code == 2, output
    assert "AL-404" in output
    assert not (repo / "ran-format.txt").exists()


@pytest.mark.ac("E11-AC-11")
def test_the_gate_runs_with_valid_packs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _gated(tmp_path, {"alpha": pack()})
    code, output = run_gate(repo, monkeypatch, capsys)
    assert code == 0, output
    assert (repo / "ran-format.txt").exists()


@pytest.mark.ac("E11-AC-11")
def test_a_kit_without_standards_py_skips_the_gate_step(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _gated(tmp_path, {"alpha": pack(name="wrong")}, with_module=False)
    code, output = run_gate(repo, monkeypatch, capsys)
    assert code == 0, output
    assert (repo / "ran-format.txt").exists()


@pytest.mark.ac("E11-AC-11")
def test_install_check_reports_pack_problems(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = write_packs(tmp_path, {"alpha": pack(name="wrong")})
    (root / CONFIG).parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(KIT_CONFIG, root / CONFIG)
    assert cli.main(["check", str(root)]) == 1
    out = capsys.readouterr()
    assert f"{ALPHA}: front matter: name: " in out.out + out.err


@pytest.mark.ac("E11-AC-11")
def test_install_check_skips_packs_for_a_kit_without_standards_py(tmp_path: Path) -> None:
    root = write_packs(tmp_path / "repo", {"alpha": pack(name="wrong")})
    empty_kit = tmp_path / "kit"
    empty_kit.mkdir()
    assert cli.standards_problems(root, empty_kit) == []
    assert cli.standards_problems(root) != []
