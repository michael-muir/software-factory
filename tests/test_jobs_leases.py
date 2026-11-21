"""E18/T1: leases: `claim`, `beat` and `release`.

Covers E18 AC-11 and AC-12. Expectations come from the E18 spec and the design note ("Leases and
heartbeats", ADR 0052), not from the implementation. The API takes `now` in Unix seconds, so
most tests use a fixed clock; the command-line tests use the real one.
"""

from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path

import pytest

import jobs
from tests._jobs import (
    MINUTE,
    T0,
    api_repo,
    call,
    index_path,
    jobs_repo,
    new,
    record,
    record_path,
    show,
)


def setup(tmp_path: Path, config: str | None = None) -> tuple[jobs.Repo, jobs.Config, str]:
    repo = api_repo(jobs_repo(tmp_path, config))
    job = jobs.new_job(repo, "Leased", now=T0)["id"]
    return repo, jobs.load_config(repo), job


def iso_seconds(text: str) -> float:
    return dt.datetime.fromisoformat(text).timestamp()


# --- AC-11: claim -----------------------------------------------------------------------------


@pytest.mark.ac("E18-AC-11")
def test_a_claim_gives_a_lease_for_lease_minutes(tmp_path: Path) -> None:
    repo, config, job = setup(tmp_path)
    assert jobs.lease_state(repo, job, now=T0) == "unclaimed"
    lease = jobs.claim(repo, config, job, "s-a", now=T0)
    assert (lease.job, lease.session) == (job, "s-a")
    assert lease.acquired == T0
    assert lease.expires == T0 + 10 * MINUTE
    assert lease.minutes == 10
    assert jobs.lease_state(repo, job, now=T0 + 10 * MINUTE - 1) == "claimed"


@pytest.mark.ac("E18-AC-11")
def test_a_claim_sets_the_owner_and_adds_one_claim_entry(tmp_path: Path) -> None:
    repo, config, job = setup(tmp_path)
    jobs.claim(repo, config, job, "s-a", now=T0 + 5)
    data = jobs.read_job(repo, job)
    assert data["owner"] == "s-a"
    assert data["claims"] == [
        {
            "session": "s-a",
            "at": dt.datetime.fromtimestamp(T0 + 5, dt.UTC),
            "forced": False,
            "from": "",
        }
    ]
    assert data["updated"] == dt.datetime.fromtimestamp(T0 + 5, dt.UTC)


@pytest.mark.ac("E18-AC-11")
def test_the_lease_length_comes_from_the_config(tmp_path: Path) -> None:
    repo, config, job = setup(tmp_path, "[jobs]\nlease_minutes = 0.5\n")
    lease = jobs.claim(repo, config, job, "s-a", now=T0)
    assert lease.expires == T0 + 30
    assert jobs.lease_state(repo, job, now=T0 + 29) == "claimed"
    assert jobs.lease_state(repo, job, now=T0 + 30) == "crashed"


@pytest.mark.ac("E18-AC-11")
def test_claim_prints_the_session_and_expiry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = jobs_repo(tmp_path)
    job = new(repo, monkeypatch, capsys)
    before = dt.datetime.now(dt.UTC).timestamp()
    code, out, err = call(repo, monkeypatch, capsys, "claim", job, "--session", "s-cli")
    assert code == 0, err
    assert "s-cli" in out
    stamps = re.findall(r"\d{4}-\d\d-\d\dT[0-9:.]+(?:Z|[+-]\d\d:\d\d)", out)
    assert len(stamps) == 1, out
    assert before + 10 * MINUTE - 2 <= iso_seconds(stamps[0]) <= before + 10 * MINUTE + 60


@pytest.mark.ac("E18-AC-11")
def test_claim_json_prints_the_lease(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = jobs_repo(tmp_path)
    job = new(repo, monkeypatch, capsys)
    code, out, err = call(repo, monkeypatch, capsys, "claim", job, "--session", "s-j", "--json")
    assert code == 0, err
    data = json.loads(out)
    assert (data["job"], data["session"], data["minutes"]) == (job, "s-j", 10)
    assert iso_seconds(data["expires"]) - iso_seconds(data["acquired"]) == pytest.approx(600)
    shown = show(repo, monkeypatch, capsys, job)
    assert shown["state"] == "claimed"
    assert shown["lease"]["session"] == "s-j"


@pytest.mark.ac("E18-AC-11")
def test_the_session_comes_from_factory_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = jobs_repo(tmp_path)
    job = new(repo, monkeypatch, capsys)
    monkeypatch.setenv("FACTORY_SESSION", "s-from-env")
    code, out, err = call(repo, monkeypatch, capsys, "claim", job)
    assert code == 0, err
    assert "s-from-env" in out
    assert record(repo, job)["owner"] == "s-from-env"
    code, _, err = call(repo, monkeypatch, capsys, "beat", job)
    assert code == 0, err


@pytest.mark.ac("E18-AC-11")
def test_a_generated_session_id_is_printed_and_owns_the_job(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = jobs_repo(tmp_path)
    job = new(repo, monkeypatch, capsys)
    monkeypatch.delenv("FACTORY_SESSION", raising=False)
    code, out, err = call(repo, monkeypatch, capsys, "claim", job)
    assert code == 0, err
    owner = record(repo, job)["owner"]
    assert re.fullmatch(r"s-[a-z0-9-]+-\d+-[0-9a-f]{4}", owner), owner
    assert owner in out


@pytest.mark.ac("E18-AC-11")
@pytest.mark.parametrize("session", ["", "has space", "x" * 65, "semi;colon"])
def test_a_bad_session_id_exits_2(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    session: str,
) -> None:
    repo = jobs_repo(tmp_path)
    job = new(repo, monkeypatch, capsys)
    assert call(repo, monkeypatch, capsys, "claim", job, "--session", session)[0] == 2
    assert record(repo, job)["owner"] == ""


@pytest.mark.ac("E18-AC-11")
def test_the_holder_claiming_again_only_renews(tmp_path: Path) -> None:
    repo, config, job = setup(tmp_path)
    jobs.claim(repo, config, job, "s-a", now=T0)
    before = jobs.read_job(repo, job)
    lease = jobs.claim(repo, config, job, "s-a", now=T0 + MINUTE)
    assert lease.expires == T0 + 11 * MINUTE
    assert jobs.read_job(repo, job) == before, "no new claim entry, no record write"


@pytest.mark.ac("E18-AC-11")
def test_a_live_lease_held_by_another_session_is_refused(tmp_path: Path) -> None:
    repo, config, job = setup(tmp_path)
    jobs.claim(repo, config, job, "s-a", now=T0)
    before = jobs.read_job(repo, job)
    with pytest.raises(jobs.Refused) as caught:
        jobs.claim(repo, config, job, "s-b", now=T0 + 10 * MINUTE - 1)
    assert "s-a" in str(caught.value)
    assert dt.datetime.fromtimestamp(T0 + 10 * MINUTE, dt.UTC).isoformat()[:16] in str(caught.value)
    assert jobs.read_job(repo, job) == before


@pytest.mark.ac("E18-AC-11")
def test_a_refused_claim_exits_1_naming_the_holder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = jobs_repo(tmp_path)
    job = new(repo, monkeypatch, capsys)
    assert call(repo, monkeypatch, capsys, "claim", job, "--session", "s-a")[0] == 0
    before = record_path(repo, job).read_bytes()
    code, _, err = call(repo, monkeypatch, capsys, "claim", job, "--session", "s-b")
    assert code == 1
    assert "s-a" in err
    assert record_path(repo, job).read_bytes() == before


@pytest.mark.ac("E18-AC-11")
def test_a_crashed_job_can_be_claimed_by_anyone(tmp_path: Path) -> None:
    repo, config, job = setup(tmp_path)
    jobs.claim(repo, config, job, "s-a", now=T0)
    assert jobs.lease_state(repo, job, now=T0 + 10 * MINUTE) == "crashed"
    lease = jobs.claim(repo, config, job, "s-b", now=T0 + 10 * MINUTE)
    assert lease.session == "s-b"
    data = jobs.read_job(repo, job)
    assert data["owner"] == "s-b"
    assert [c["session"] for c in data["claims"]] == ["s-a", "s-b"]
    assert data["claims"][-1]["forced"] is False


@pytest.mark.ac("E18-AC-11")
def test_force_takes_a_live_lease_and_the_record_says_so(tmp_path: Path) -> None:
    repo, config, job = setup(tmp_path)
    jobs.claim(repo, config, job, "s-a", now=T0)
    lease = jobs.claim(repo, config, job, "s-b", force=True, now=T0 + MINUTE)
    assert lease.session == "s-b"
    assert lease.expires == T0 + 11 * MINUTE
    last = jobs.read_job(repo, job)["claims"][-1]
    assert (last["session"], last["forced"], last["from"]) == ("s-b", True, "s-a")
    with pytest.raises(jobs.Refused):
        jobs.beat(repo, config, job, "s-a", now=T0 + 2 * MINUTE)


@pytest.mark.ac("E18-AC-11")
def test_force_on_the_command_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = jobs_repo(tmp_path)
    job = new(repo, monkeypatch, capsys)
    assert call(repo, monkeypatch, capsys, "claim", job, "--session", "s-a")[0] == 0
    code, _, err = call(repo, monkeypatch, capsys, "claim", job, "--session", "s-b", "--force")
    assert code == 0, err
    last = record(repo, job)["claims"][-1]
    assert (last["session"], last["forced"], last["from"]) == ("s-b", True, "s-a")


@pytest.mark.ac("E18-AC-11")
@pytest.mark.parametrize("status", ["done", "cancelled"])
def test_a_done_or_cancelled_job_cannot_be_claimed(tmp_path: Path, status: str) -> None:
    repo, config, job = setup(tmp_path)
    jobs.claim(repo, config, job, "s-a", now=T0)
    jobs.set_job(repo, job, "s-a", now=T0, status=status)
    jobs.release(repo, job, "s-a")
    with pytest.raises(jobs.Refused):
        jobs.claim(repo, config, job, "s-b", now=T0 + MINUTE)
    with pytest.raises(jobs.Refused):
        jobs.claim(repo, config, job, "s-b", force=True, now=T0 + MINUTE)
    assert jobs.lease_state(repo, job, now=T0 + MINUTE) == status


# --- AC-12: beat and release ------------------------------------------------------------------


@pytest.mark.ac("E18-AC-12")
def test_beat_renews_the_holders_lease(tmp_path: Path) -> None:
    repo, config, job = setup(tmp_path)
    jobs.claim(repo, config, job, "s-a", now=T0)
    before = jobs.read_job(repo, job)
    lease = jobs.beat(repo, config, job, "s-a", now=T0 + 9 * MINUTE)
    assert lease.expires == T0 + 19 * MINUTE
    assert jobs.lease_state(repo, job, now=T0 + 18 * MINUTE) == "claimed"
    assert jobs.read_job(repo, job) == before, "a heartbeat doesn't rewrite the record"


@pytest.mark.ac("E18-AC-12")
def test_beat_by_anyone_else_is_refused(tmp_path: Path) -> None:
    repo, config, job = setup(tmp_path)
    with pytest.raises(jobs.Refused):
        jobs.beat(repo, config, job, "s-a", now=T0)  # no lease, and not the owner
    jobs.claim(repo, config, job, "s-a", now=T0)
    with pytest.raises(jobs.Refused):
        jobs.beat(repo, config, job, "s-b", now=T0 + MINUTE)
    assert jobs.lease_state(repo, job, now=T0 + 10 * MINUTE) == "crashed", "s-b renewed nothing"


@pytest.mark.ac("E18-AC-12")
def test_the_holder_may_renew_an_expired_lease_no_one_has_claimed(tmp_path: Path) -> None:
    repo, config, job = setup(tmp_path)
    jobs.claim(repo, config, job, "s-a", now=T0)
    lease = jobs.beat(repo, config, job, "s-a", now=T0 + 15 * MINUTE)
    assert lease.expires == T0 + 25 * MINUTE
    assert jobs.lease_state(repo, job, now=T0 + 15 * MINUTE) == "claimed"


@pytest.mark.ac("E18-AC-12")
def test_beat_and_release_on_the_command_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = jobs_repo(tmp_path)
    job = new(repo, monkeypatch, capsys)
    session = ("--session", "s-a")
    assert call(repo, monkeypatch, capsys, "claim", job, *session)[0] == 0
    code, out, err = call(repo, monkeypatch, capsys, "beat", job, *session, "--json")
    assert code == 0, err
    assert json.loads(out)["session"] == "s-a"
    assert call(repo, monkeypatch, capsys, "beat", job, "--session", "s-b")[0] == 1
    assert call(repo, monkeypatch, capsys, "release", job, "--session", "s-b")[0] == 1
    code, _, err = call(repo, monkeypatch, capsys, "release", job, *session)
    assert code == 0, err
    assert show(repo, monkeypatch, capsys, job)["state"] == "unclaimed"
    assert show(repo, monkeypatch, capsys, job)["lease"] is None
    assert call(repo, monkeypatch, capsys, "release", job, *session)[0] == 1


@pytest.mark.ac("E18-AC-12")
def test_after_release_anyone_may_claim_without_force(tmp_path: Path) -> None:
    repo, config, job = setup(tmp_path)
    jobs.claim(repo, config, job, "s-a", now=T0)
    jobs.release(repo, job, "s-a")
    assert jobs.lease_state(repo, job, now=T0 + 1) == "unclaimed"
    lease = jobs.claim(repo, config, job, "s-b", now=T0 + 1)
    assert lease.session == "s-b"
    assert jobs.read_job(repo, job)["claims"][-1]["forced"] is False


@pytest.mark.ac("E18-AC-12")
def test_release_by_anyone_else_is_refused(tmp_path: Path) -> None:
    repo, config, job = setup(tmp_path)
    with pytest.raises(jobs.Refused):
        jobs.release(repo, job, "s-a")
    jobs.claim(repo, config, job, "s-a", now=T0)
    with pytest.raises(jobs.Refused):
        jobs.release(repo, job, "s-b")
    assert jobs.lease_state(repo, job, now=T0) == "claimed"


@pytest.mark.ac("E18-AC-12")
def test_the_owner_takes_back_a_lease_lost_with_the_index(tmp_path: Path) -> None:
    root = jobs_repo(tmp_path)
    repo = api_repo(root)
    config = jobs.load_config(repo)
    job = jobs.new_job(repo, "Lost", now=T0)["id"]
    jobs.claim(repo, config, job, "s-a", now=T0)
    index_path(root).unlink()
    assert jobs.lease_state(repo, job, now=T0 + 1) == "unclaimed"
    with pytest.raises(jobs.Refused):
        jobs.beat(repo, config, job, "s-b", now=T0 + 1)  # not the record's owner
    lease = jobs.beat(repo, config, job, "s-a", now=T0 + 2)
    assert (lease.session, lease.expires) == ("s-a", T0 + 2 + 10 * MINUTE)
    assert jobs.lease_state(repo, job, now=T0 + 3) == "claimed"
