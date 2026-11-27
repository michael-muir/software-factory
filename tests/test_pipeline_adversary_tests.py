"""E13-T9: the Adversary's new attack tests pass the end of review, and reviewers get the headings.

Covers E13 AC-13 and AC-07, as amended on 27 Nov 2026 by the product owner's decisions on #115.
In the resumed live run on #82, all six reviews passed, then `check review` stopped the job: the
Adversary had written its attack test in a new file under `tests/` after the gated commit. The
docs stage gates the new head again before the PR, so now:

- at the end of review, files added under `tests/` since the gated commit pass, besides anything
  under `.agentic/`; a modified or deleted file, or any other new file, still needs a fresh gate;
- the check before each pending reviewer keeps the stricter rule (only `.agentic/`);
- the prompt for a role without a shell names the handoff headings exactly, in order, and the
  Verifier's verdict line still ends its reply, after the handoff note.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

import pipeline
from tests._pipeline import REVIEWERS, TASK, TASK_REL, commit, gate_report, git, repo
from tests._pipeline import task_text as plan_task_text
from tests._pipeline_driver import calls, read
from tests._pipeline_slices import (
    gate_calls,
    one_task_plan,
    slice_turns,
    start,
    task_entry,
    to_slices,
    turns,
)

AC13 = "E13-AC-13"
AC07 = "E13-AC-07"
ATTACK = "tests/test_attack_widgets.py"
ATTACK_TEXT = "def test_widgets_resist_attack() -> None:\n    assert True\n"
HEADINGS = ("## Done", "## Next", "## Open questions")


def roles(log: Path) -> list[str]:
    return [c["role"] for c in calls(log)]


def drive(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    reviews: dict[str, Any],
) -> tuple[Path, Path, int]:
    """Run a one-task job to its end, with these reviewers' turns."""
    script = turns(one_task_plan(), slice_turns(), reviews)
    root, _, log = start(tmp_path, monkeypatch, capsys, script)
    return root, log, to_slices(root, monkeypatch, capsys)


def attack(files: dict[str, str], message: str = "test(E31-T1): attack tests") -> list[Any]:
    """A reviewer's turn that writes these files and commits them (the Adversary has a shell)."""
    return [{"write": files}, {"commit": message}]


# --- AC-13: the end of review, driven ----------------------------------------------------------


@pytest.mark.ac(AC13)
def test_the_adversary_s_new_attack_test_passes_review_and_the_docs_stage_gates_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root, log, code = drive(
        tmp_path, monkeypatch, capsys, {"adversary": [attack({ATTACK: ATTACK_TEXT})]}
    )
    assert code == 0, read(root).get("reason")
    record = read(root)
    assert record["status"] == "awaiting-merge"
    assert "docs-writer" in roles(log)
    shipped = str(task_entry(root)["head"])
    assert git(root, "show", f"{shipped}:{ATTACK}") == ATTACK_TEXT.rstrip("\n")
    gates = record["gates"]
    assert len(gates) == 2 and len(gate_calls(tmp_path)) == 2
    assert gates[-1]["commit"] == shipped and gates[-1]["verdict"] == "pass"
    first = gates[0]["commit"]
    added = git(root, "diff", "--name-only", "--diff-filter=A", first, gates[-1]["commit"])
    assert ATTACK in added.split()


@pytest.mark.ac(AC13)
def test_the_adversary_changing_an_existing_test_still_stops_the_job(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    changed = {"tests/test_widgets.py": "def test_widgets() -> None:\n    assert 1\n"}
    root, log, code = drive(tmp_path, monkeypatch, capsys, {"adversary": [attack(changed)]})
    assert code == 1
    record = read(root)
    assert (record["status"], record["stage"]) == ("needs-human", "review")
    assert "tests/test_widgets.py" in record["reason"]
    assert "docs-writer" not in roles(log)


@pytest.mark.ac(AC13)
def test_the_adversary_adding_a_file_outside_tests_still_stops_the_job(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root, log, code = drive(
        tmp_path, monkeypatch, capsys, {"adversary": [attack({"attack_helper.py": "X = 1\n"})]}
    )
    assert code == 1
    record = read(root)
    assert (record["status"], record["stage"]) == ("needs-human", "review")
    assert "attack_helper.py" in record["reason"]
    assert "docs-writer" not in roles(log)


@pytest.mark.ac(AC13)
def test_a_new_test_before_a_pending_reviewer_still_stops_the_review_stage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root, log, code = drive(
        tmp_path, monkeypatch, capsys, {"spec-reviewer": [attack({ATTACK: ATTACK_TEXT})]}
    )
    assert code == 1
    record = read(root)
    assert (record["status"], record["stage"]) == ("needs-human", "review")
    assert ATTACK in record["reason"]
    after = REVIEWERS[REVIEWERS.index("spec-reviewer") + 1 :]
    assert not any(role in roles(log) for role in after)


# --- AC-13: `check review` ----------------------------------------------------------------------


def check_review(root: Path, report: dict[str, Any] | None) -> list[pipeline.Problem]:
    checkout = pipeline.Checkout(
        root=root, epic="E31", task=TASK, reviews=REVIEWERS, gate_report=report
    )
    return pipeline.check("review", checkout)


def gated(tmp_path: Path) -> tuple[Path, str]:
    """A repo with a test file, gated at its head, then its task file committed in round 1."""
    root = repo(tmp_path)
    gated_at = commit(root, {"tests/test_widgets.py": "def test_w() -> None:\n    pass\n"})
    commit(root, {TASK_REL: plan_task_text(review_round=1)}, "chore: review round 1")
    return root, gated_at


def gate_problems(problems: list[pipeline.Problem]) -> list[pipeline.Problem]:
    return [p for p in problems if p.path == "gate report"]


@pytest.mark.ac(AC13)
@pytest.mark.parametrize("rel", [ATTACK, "tests/attacks/test_deep.py", "tests/fixtures/x.txt"])
def test_check_review_passes_when_files_were_added_under_tests_since_the_report(
    tmp_path: Path, rel: str
) -> None:
    root, gated_at = gated(tmp_path)
    commit(root, {rel: ATTACK_TEXT}, "test: attack")
    assert check_review(root, gate_report(gated_at)) == []


@pytest.mark.ac(AC13)
def test_check_review_passes_with_new_tests_and_agentic_changes_together(tmp_path: Path) -> None:
    root, gated_at = gated(tmp_path)
    commit(root, {ATTACK: ATTACK_TEXT, ".agentic/handoffs/x.md": "## Done\n"}, "test: attack")
    assert check_review(root, gate_report(gated_at)) == []


@pytest.mark.ac(AC13)
def test_check_review_fails_when_an_existing_test_was_modified(tmp_path: Path) -> None:
    root, gated_at = gated(tmp_path)
    commit(root, {"tests/test_widgets.py": "def test_w() -> None:\n    assert 1\n"})
    problems = check_review(root, gate_report(gated_at))
    assert len(problems) == 1 and problems[0].path == "gate report"
    assert "tests/test_widgets.py" in problems[0].message


@pytest.mark.ac(AC13)
def test_check_review_fails_when_an_existing_test_was_deleted(tmp_path: Path) -> None:
    root, gated_at = gated(tmp_path)
    git(root, "rm", "-q", "tests/test_widgets.py")
    git(root, "commit", "-q", "-m", "test: drop")
    problems = gate_problems(check_review(root, gate_report(gated_at)))
    assert len(problems) == 1 and "tests/test_widgets.py" in problems[0].message


@pytest.mark.ac(AC13)
def test_check_review_fails_when_an_existing_test_was_renamed(tmp_path: Path) -> None:
    root, gated_at = gated(tmp_path)
    git(root, "mv", "tests/test_widgets.py", "tests/test_widgets_renamed.py")
    git(root, "commit", "-q", "-m", "test: rename")
    problems = gate_problems(check_review(root, gate_report(gated_at)))
    assert len(problems) == 1 and "tests/test_widgets.py" in problems[0].message


@pytest.mark.ac(AC13)
@pytest.mark.parametrize("rel", ["attack.py", "src/tests/test_x.py", "docs/tests/test_x.py"])
def test_check_review_fails_when_a_new_file_is_not_under_tests(tmp_path: Path, rel: str) -> None:
    root, gated_at = gated(tmp_path)
    commit(root, {rel: ATTACK_TEXT}, "test: attack")
    problems = gate_problems(check_review(root, gate_report(gated_at)))
    assert len(problems) == 1 and rel in problems[0].message


@pytest.mark.ac(AC13)
def test_check_review_still_needs_the_report_s_commit_on_the_branch(tmp_path: Path) -> None:
    root, _ = gated(tmp_path)
    commit(root, {ATTACK: ATTACK_TEXT}, "test: attack")
    problems = gate_problems(check_review(root, gate_report("0" * 40)))
    assert len(problems) == 1


@pytest.mark.ac(AC13)
def test_check_review_still_needs_a_green_report(tmp_path: Path) -> None:
    root, gated_at = gated(tmp_path)
    commit(root, {ATTACK: ATTACK_TEXT}, "test: attack")
    problems = gate_problems(check_review(root, gate_report(gated_at, verdict="fail")))
    assert len(problems) == 1


@pytest.mark.ac(AC13)
def test_the_stricter_rule_before_each_reviewer_refuses_a_new_test(tmp_path: Path) -> None:
    root, gated_at = gated(tmp_path)
    commit(root, {ATTACK: ATTACK_TEXT}, "test: attack")
    checkout = pipeline.Checkout(
        root=root, epic="E31", task=TASK, reviews=REVIEWERS, gate_report=gate_report(gated_at)
    )
    strict = pipeline._gate_for_review(checkout)
    assert len(strict) == 1 and ATTACK in strict[0][1]
    assert pipeline._gate_for_review(checkout, allow_added_tests=True) == []


# --- AC-07: the handoff headings ----------------------------------------------------------------


def heading_positions(text: str) -> list[int]:
    return [text.index(f"`{h}`") for h in HEADINGS]


@pytest.mark.ac(AC07)
@pytest.mark.parametrize("role", ["verifier", "spec-reviewer"])
def test_a_role_without_a_shell_is_told_the_three_headings_in_order(role: str) -> None:
    text = pipeline.prompt("review", role, job="j", epic="E31", task="E31-T1", shell=False)
    places = heading_positions(text)
    assert places == sorted(places)
    assert text.splitlines()[-1] == pipeline.NO_SHELL_LAST_LINE


@pytest.mark.ac(AC07)
def test_a_role_with_a_shell_is_not_told_the_headings() -> None:
    text = pipeline.prompt("build", "implementer", job="j", epic="E31", task="E31-T1", shell=True)
    assert not any(f"`{h}`" in text for h in HEADINGS)


@pytest.mark.ac(AC07)
def test_the_verifier_s_verdict_still_ends_its_reply_after_the_handoff_note() -> None:
    assert "after your handoff note" in pipeline.VERDICT_ASK
    text = pipeline.prompt(
        "review",
        "verifier",
        job="j",
        epic="E31",
        task="E31-T1",
        extra=[pipeline.VERDICT_ASK],
        shell=False,
    )
    assert pipeline.VERDICT_ASK in text
    places = heading_positions(text)
    assert places == sorted(places)
    assert not any(h in pipeline.VERDICT_ASK for h in HEADINGS)


@pytest.mark.ac(AC07)
def test_every_reviewer_without_a_shell_gets_the_headings_in_a_driven_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root, log, code = drive(tmp_path, monkeypatch, capsys, {})
    assert code == 0
    seen = []
    for entry in calls(log):
        if entry["role"] in REVIEWERS and not pipeline.has_shell(root, entry["role"]):
            places = heading_positions(entry["prompt"])
            assert places == sorted(places), entry["role"]
            seen.append(entry["role"])
    assert seen == [r for r in REVIEWERS if r != "adversary"]


@pytest.mark.ac(AC07)
def test_the_headings_named_are_the_ones_the_driver_looks_for() -> None:
    assert pipeline.HANDOFF_HEADINGS == HEADINGS
