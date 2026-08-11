"""Per-file confirmation in `fetch`. No network, no password.

The property that matters: a declined file must never open a link. The confirm
question is asked before SyncLink(...) is constructed, so these tests would blow
up on a real connection attempt -- site_urls is deliberately unusable.
"""

from __future__ import annotations

import os

import pytest

from sync_tdc_logs.download import ALL, NO, QUIT, YES, Outcome, human, run

# If run() ever tries to open a link, this URL makes it fail loudly rather than
# quietly reaching the network.
UNUSABLE = {"008": "not-a-sync-link", "017": "not-a-sync-link"}


def job(site: str, name: str, size: int = 1000) -> tuple[str, dict]:
    return (
        site,
        {
            "site": site,
            "session": f"{site}_01-001",
            "name": name,
            "size": size,
            "sync_id": 1,
            "cachekey": "60:aa",
            "enc_data_key": "",
            "enc_share_name": "1:aa",
            "remote_path": f"TDC Sessions/{site}_01-001 TDC Sessions/applog/{name}",
            "share_id": "26395930000",
            "blob_id": 25215439850003,
        },
    )


JOBS = [job("008", "a.zip"), job("008", "b.zip"), job("017", "c.zip")]


def test_declining_everything_touches_no_network(tmp_path) -> None:
    asked = []

    def confirm(index, count, site, entry, dest):
        asked.append((index, count, site, entry["name"], dest))
        return NO

    outcome = run(JOBS, UNUSABLE, str(tmp_path), "pw", confirm=confirm)

    assert outcome.declined == 3
    assert outcome.downloaded == 0
    assert outcome.failed == 0, "a declined file must not even try to connect"
    assert [a[0] for a in asked] == [1, 2, 3]
    assert [a[1] for a in asked] == [3, 3, 3]
    assert [a[3] for a in asked] == ["a.zip", "b.zip", "c.zip"]
    assert os.listdir(tmp_path) == []


def test_quit_declines_the_rest_including_the_current_file(tmp_path) -> None:
    """'q' on file 2 of 3 must leave 2 undecided, not 1."""
    calls = []

    def confirm(index, count, site, entry, dest):
        calls.append(index)
        return QUIT if index == 2 else NO

    outcome = run(JOBS, UNUSABLE, str(tmp_path), "pw", confirm=confirm)

    assert calls == [1, 2], "must stop asking after quit"
    assert outcome.declined == 3  # 1 declined outright + 2 undecided
    assert outcome.downloaded == 0


def test_confirm_sees_enough_to_decide(tmp_path) -> None:
    """The prompt needs the name, site, session, size and remote path."""
    seen: dict = {}

    def confirm(index, count, site, entry, dest):
        seen.update(entry)
        return NO

    run([JOBS[0]], UNUSABLE, str(tmp_path), "pw", confirm=confirm)

    for key in ("name", "site", "session", "size", "remote_path"):
        assert seen.get(key), f"confirm cannot show {key}"


def test_already_present_files_are_not_asked_about(tmp_path) -> None:
    """No point asking about something the destination already holds."""
    (tmp_path / "a.zip").write_bytes(b"x")
    asked = []

    def confirm(index, count, site, entry, dest):
        asked.append(entry["name"])
        return NO

    outcome = run([JOBS[0]], UNUSABLE, str(tmp_path), "pw", confirm=confirm)

    assert asked == []
    assert outcome.skipped == 1
    assert outcome.declined == 0


def test_all_stops_asking_but_then_needs_the_network(tmp_path) -> None:
    """'a' approves the rest; with an unusable URL that surfaces as failures.

    Proves ALL really does stop asking rather than silently declining.
    """
    asked = []

    def confirm(index, count, site, entry, dest):
        asked.append(index)
        return ALL

    outcome = run(JOBS, UNUSABLE, str(tmp_path), "pw", confirm=confirm)

    assert asked == [1], "ALL must suppress every later question"
    assert outcome.declined == 0
    assert outcome.failed == 3, "approved files were attempted (and failed on the URL)"


def test_confirm_none_means_approve_all(tmp_path) -> None:
    """The --yes path. Must be an explicit choice, never a fallback."""
    outcome = run(JOBS, UNUSABLE, str(tmp_path), "pw", confirm=None)

    assert outcome.declined == 0
    assert outcome.failed == 3


def test_a_stale_plan_is_reported_not_attempted(tmp_path) -> None:
    site, entry = job("008", "old.zip")
    del entry["share_id"]

    outcome = run([(site, entry)], UNUSABLE, str(tmp_path), "pw", confirm=None)

    assert outcome.failed == 1
    assert outcome.downloaded == 0


@pytest.mark.parametrize(
    "size,expected",
    [(0, "0.0 B"), (1024, "1.0 KB"), (63_666_855, "60.7 MB")],
)
def test_human(size: int, expected: str) -> None:
    assert human(size) == expected


def test_exit_code_reflects_failures_not_declines() -> None:
    """Declining is a choice, not an error -- it must not fail the command."""
    assert Outcome(declined=5).exit_code == 0
    assert Outcome(failed=1).exit_code == 1


def test_yes_and_no_are_distinct_answers() -> None:
    assert len({YES, NO, ALL, QUIT}) == 4
