"""E11/T2: the 12 kit standards packs.

Covers E11 AC-05 and AC-06. Expectations come from the E11 spec ("The packs" table, AC-05 and
AC-06), the design note and ADR 0037, not from the packs themselves.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

import standards
from tests._ac import REPO_ROOT
from tests._repo import KIT_FILES

KIT = REPO_ROOT / "kit"
KIT_STANDARDS = KIT / ".factory" / "standards"
CPP = ["*.cc", "*.cpp", "*.cxx", "*.h", "*.hh", "*.hpp"]
GOOGLE = "https://google.github.io/styleguide/"

# name: (prefix, applies_to, detect, replaces, source URLs the pack must name)
PACKS: dict[str, tuple[str, list[str], list[str], list[str], list[str]]] = {
    "python": (
        "PY",
        ["*.py", "*.pyi"],
        [],
        [],
        [
            "https://peps.python.org/pep-0008/",
            "https://peps.python.org/pep-0257/",
            "https://peps.python.org/pep-0484/",
        ],
    ),
    "typescript": (
        "TS",
        ["*.ts", "*.tsx", "*.mts", "*.cts"],
        [],
        [],
        [GOOGLE + "tsguide.html"],
    ),
    "javascript": (
        "JS",
        ["*.js", "*.jsx", "*.mjs", "*.cjs"],
        [],
        [],
        [GOOGLE + "jsguide.html"],
    ),
    "cpp": ("CPP", CPP, [], [], [GOOGLE + "cppguide.html"]),
    "go": ("GO", ["*.go"], [], [], ["https://github.com/uber-go/guide/blob/master/style.md"]),
    "rust": ("RS", ["*.rs"], [], [], ["https://rust-lang.github.io/api-guidelines/"]),
    "csharp": (
        "CS",
        ["*.cs"],
        [],
        [],
        [
            "https://github.com/DotNetAnalyzers/StyleCopAnalyzers/",
            "https://learn.microsoft.com/en-us/dotnet/standard/design-guidelines/",
        ],
    ),
    "lua": ("LUA", ["*.lua"], [], [], ["https://github.com/Olivine-Labs/lua-style-guide"]),
    "unreal": (
        "UE",
        CPP,
        ["*.uproject"],
        ["cpp"],
        [
            "https://dev.epicgames.com/documentation/en-us/unreal-engine/"
            "epic-cplusplus-coding-standard-for-unreal-engine"
        ],
    ),
    "shell": ("SH", ["*.sh", "*.bash"], [], [], [GOOGLE + "shellguide.html"]),
    "tests": ("TST", ["*"], [], [], []),
    "docs": ("DOC", ["*"], [], [], ["https://www.conventionalcommits.org/"]),
}
NAMES = sorted(PACKS)
SEVERITIES = ("blocker", "major", "minor")


def read(name: str) -> standards.Pack:
    rel = f".factory/standards/{name}/rules.md"
    pack, found = standards.read_pack(KIT / rel, rel)
    assert found == [], found
    assert pack is not None
    return pack


# --- AC-05: exactly the 12 packs, as the spec's table gives them -------------------------------


@pytest.mark.ac("E11-AC-05")
def test_the_kit_ships_exactly_the_twelve_packs_and_the_house_seed() -> None:
    folders = {p.name for p in KIT_STANDARDS.iterdir() if p.is_dir() and p.name != "__pycache__"}
    assert folders == set(PACKS) | {"house"}
    for name in PACKS:
        assert (KIT_STANDARDS / name / "rules.md").is_file(), name


@pytest.mark.ac("E11-AC-05")
def test_the_gitkeep_is_gone() -> None:
    assert not (KIT_STANDARDS / ".gitkeep").exists()
    assert ".factory/standards/.gitkeep" not in KIT_FILES


@pytest.mark.ac("E11-AC-05")
def test_every_pack_is_a_kit_file() -> None:
    for name in PACKS:
        assert f".factory/standards/{name}/rules.md" in KIT_FILES, name


@pytest.mark.ac("E11-AC-05")
@pytest.mark.parametrize("name", NAMES)
def test_each_pack_has_the_specs_name_prefix_and_globs(name: str) -> None:
    prefix, applies_to, detect, replaces, _ = PACKS[name]
    pack = read(name)
    assert (pack.name, pack.prefix) == (name, prefix)
    assert pack.applies_to == applies_to
    assert pack.detect == detect
    assert pack.replaces == replaces


@pytest.mark.ac("E11-AC-05")
@pytest.mark.parametrize("name", NAMES)
def test_each_pack_names_the_specs_main_sources(name: str) -> None:
    urls = [s.url for s in read(name).sources]
    for url in PACKS[name][4]:
        assert url in urls, (name, urls)


@pytest.mark.ac("E11-AC-05")
def test_unreal_replaces_cpp_only_in_a_repo_with_a_uproject() -> None:
    unreal = read("unreal")
    assert unreal.detect == ["*.uproject"]
    assert unreal.replaces == ["cpp"]


@pytest.mark.ac("E11-AC-05")
@pytest.mark.parametrize("name", ["tests", "docs"])
def test_tests_and_docs_apply_to_every_path(name: str) -> None:
    assert read(name).applies_to == ["*"]


# --- AC-06: each pack's shape and size -------------------------------------------------------


@pytest.mark.ac("E11-AC-06")
def test_the_kit_packs_pass_standards_check_together(tmp_path: Path) -> None:
    shutil.copytree(KIT_STANDARDS, tmp_path / ".factory" / "standards")
    assert [str(p) for p in standards.validate(tmp_path)] == []


@pytest.mark.ac("E11-AC-06")
@pytest.mark.parametrize("name", NAMES)
def test_each_pack_has_15_to_30_rules_in_force(name: str) -> None:
    in_force = [r for r in read(name).rules if r.severity != "retired"]
    assert 15 <= len(in_force) <= 30, (name, len(in_force))


@pytest.mark.ac("E11-AC-06")
@pytest.mark.parametrize("name", NAMES)
def test_each_pack_uses_every_severity(name: str) -> None:
    used = {r.severity for r in read(name).rules}
    assert set(SEVERITIES) <= used, (name, used)


@pytest.mark.ac("E11-AC-06")
@pytest.mark.parametrize("name", NAMES)
def test_each_source_records_its_licence(name: str) -> None:
    sources = read(name).sources
    assert sources
    assert all(s.licence.strip() for s in sources), sources


@pytest.mark.ac("E11-AC-06")
@pytest.mark.parametrize("name", NAMES)
def test_every_source_is_cited_by_a_rule(name: str) -> None:
    pack = read(name)
    cited = {s.url for s in pack.sources if any(r.source.startswith(s.url) for r in pack.rules)}
    assert cited == {s.url for s in pack.sources}, name
