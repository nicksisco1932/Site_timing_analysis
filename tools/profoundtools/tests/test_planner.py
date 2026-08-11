"""Planner logic against a fake share. No network, no password.

The case that matters is the duplicate trap: Sapporo session folders whose
numbering disagrees with the zips inside them. Joining on the folder name alone
put seven already-held files on the download list.
"""

from __future__ import annotations

import pytest

from sync_tdc_logs.archive import Archive
from sync_tdc_logs.planner import (
    APPLOG_DIR,
    SESSION_ROOT_DIRS,
    TDC_DATA_DIR,
    plan_site,
)
from sync_tdc_logs.synclink import Item


class FakeLink:
    """Minimal stand-in for SyncLink: a nested dict of folder -> children."""

    def __init__(self, tree: dict):
        self.root_sync_id = 0
        self._children: dict[int, list[Item]] = {}
        self.listdir_calls = 0
        self._build(tree, self.root_sync_id)

    def _build(self, node: dict, sync_id: int) -> None:
        children: list[Item] = []
        for name, value in node.items():
            child_id = len(self._children) * 100 + len(children) + 1
            is_dir = isinstance(value, dict)
            children.append(
                Item(
                    sync_id=child_id,
                    name=name,
                    is_dir=is_dir,
                    size=0 if is_dir else int(value),
                    cachekey=f"ck{child_id}",
                    enc_data_key="" if is_dir else f"2:dk{child_id}",
                    enc_share_name=f"1:sn{child_id}",
                )
            )
        self._children[sync_id] = children
        for item, value in zip(children, node.values()):
            if item.is_dir:
                self._build(value, item.sync_id)

    def listdir(self, sync_id=None):
        self.listdir_calls += 1
        return self._children.get(self.root_sync_id if sync_id is None else sync_id, [])

    def find(self, sync_id, name):
        target = name.strip().lower()
        return next(
            (i for i in self.listdir(sync_id) if i.name.strip().lower() == target), None
        )


def _archive(*filenames: str) -> Archive:
    archive = Archive(root="(test)")
    for name in filenames:
        archive.filenames.add(name.casefold())
        from sync_tdc_logs.sessions import session_key

        key = session_key(name)
        if key:
            archive.by_session.setdefault(key, []).append(name)
    return archive


ENTRY = {"url": "https://ln5.sync.com/dl/abc/a-b-c-d", "clinic": "Test Clinic"}


def test_mislabelled_folder_does_not_redownload_a_held_file() -> None:
    """Folder says 065, the zip inside says 064, and we already hold 064."""
    link = FakeLink(
        {
            TDC_DATA_DIR: {
                "007_01-065 TDC Sessions": {
                    APPLOG_DIR: {"007_01-064 Tdc.2024_08_20.zip": 55_600_000}
                }
            }
        }
    )
    archive = _archive("007_01-064 Tdc.2024_08_20.zip")

    plan = plan_site("007", ENTRY, "pw", archive, link=link)

    assert plan.error is None
    assert plan.files == [], "already-held file must not be queued"
    assert len(plan.skipped) == 1
    assert "exact filename already held" in plan.skipped[0]
    # The folder key still counts as missing -- that is the honest report.
    assert plan.missing == ["007_01-065"]


def test_session_key_match_skips_a_renamed_file() -> None:
    """Same session, different filename: caught by session key, not filename."""
    link = FakeLink(
        {
            TDC_DATA_DIR: {
                "007_01-076 TDC Sessions": {
                    APPLOG_DIR: {"007_01-079 Tdc.2024_10_30.zip": 58_100_000}
                }
            }
        }
    )
    # A different filename for the same session.
    archive = _archive("007_01-079 Tdc.2024_11_12.zip")

    plan = plan_site("007", ENTRY, "pw", archive, link=link)

    assert plan.files == []
    assert len(plan.skipped) == 1
    assert "folder said 007_01-076, file says 007_01-079" in plan.skipped[0]


def test_genuinely_missing_file_is_queued() -> None:
    link = FakeLink(
        {
            TDC_DATA_DIR: {
                "007_01-200 TDC Sessions": {
                    APPLOG_DIR: {"007_01-200 Tdc.2026_08_01.zip": 1234}
                }
            }
        }
    )
    plan = plan_site("007", ENTRY, "pw", _archive(), link=link)

    assert len(plan.files) == 1
    queued = plan.files[0]
    assert queued.name == "007_01-200 Tdc.2026_08_01.zip"
    assert queued.session == "007_01-200"
    assert queued.size == 1234
    assert queued.remote_path == (
        f"{TDC_DATA_DIR}/007_01-200 TDC Sessions/{APPLOG_DIR}/"
        f"007_01-200 Tdc.2026_08_01.zip"
    )
    assert plan.total_bytes == 1234


def test_held_session_costs_no_extra_calls() -> None:
    """A session we already hold must not be walked into. That is the whole point."""
    link = FakeLink(
        {
            TDC_DATA_DIR: {
                "007_01-001 TDC Sessions": {APPLOG_DIR: {"007_01-001 Tdc.zip": 10}},
                "007_01-002 TDC Sessions": {APPLOG_DIR: {"007_01-002 Tdc.zip": 10}},
            }
        }
    )
    archive = _archive("007_01-001 Tdc.zip", "007_01-002 Tdc.zip")

    plan = plan_site("007", ENTRY, "pw", archive, link=link)

    assert plan.already_held == 2
    assert plan.missing == []
    # find(root) + listdir(TDC Data) only: never descended into either session.
    assert link.listdir_calls == 2


def test_empty_applog_reports_session_folder_contents() -> None:
    """Sapporo has 24 sessions like this; the note must say where else to look."""
    link = FakeLink(
        {
            TDC_DATA_DIR: {
                "007_01-101 TDC Sessions": {
                    APPLOG_DIR: {},
                    "images": {},
                    "007_01-101 TDC Sessions.zip": 999,
                }
            }
        }
    )
    plan = plan_site("007", ENTRY, "pw", _archive(), link=link)

    assert plan.files == []
    assert len(plan.notes) == 1
    note = plan.notes[0]
    assert "applog is empty" in note
    assert "session folder holds" in note
    assert "007_01-101 TDC Sessions.zip" in note


def test_applog_with_no_zip_lists_what_it_holds() -> None:
    link = FakeLink(
        {
            TDC_DATA_DIR: {
                "007_01-102 TDC Sessions": {
                    APPLOG_DIR: {"Tdc.log": 42, "nested": {}},
                }
            }
        }
    )
    plan = plan_site("007", ENTRY, "pw", _archive(), link=link)

    note = plan.notes[0]
    assert "no .zip in applog" in note
    assert "Tdc.log" in note and "nested/" in note


def test_unparsed_folder_is_reported_not_dropped() -> None:
    link = FakeLink({TDC_DATA_DIR: {"007_2.9_Session 001": {APPLOG_DIR: {}}}})
    plan = plan_site("007", ENTRY, "pw", _archive(), link=link)

    assert plan.files == []
    assert any("unparsed session folder" in n for n in plan.notes)


def test_multiple_zips_are_all_queued_and_flagged() -> None:
    link = FakeLink(
        {
            TDC_DATA_DIR: {
                "007_01-300 TDC Sessions": {
                    APPLOG_DIR: {
                        "007_01-300 Tdc.2026_01_01.zip": 10,
                        "007_01-300 Tdc.2026_01_02.zip": 20,
                    }
                }
            }
        }
    )
    plan = plan_site("007", ENTRY, "pw", _archive(), link=link)

    assert len(plan.files) == 2
    assert any("2 zips in applog" in n for n in plan.notes)


def test_either_container_name_is_accepted() -> None:
    """Most sites call it 'TDC Sessions'; 007 and 119 call it 'TDC Data'.

    Assuming a single name made 39 of 65 sites report a spurious error.
    """
    for container in SESSION_ROOT_DIRS:
        link = FakeLink(
            {
                container: {
                    "001_01-167 TDC Sessions": {
                        APPLOG_DIR: {"001_01-167 Tdc.zip": 500}
                    }
                }
            }
        )
        plan = plan_site("001", ENTRY, "pw", _archive(), link=link)

        assert plan.error is None, f"{container}: {plan.error}"
        assert plan.remote_sessions == 1, container
        assert len(plan.files) == 1, container
        # The note/path must quote the real container, not a hardcoded default.
        assert plan.files[0].remote_path.startswith(f"{container}/"), container


def test_both_containers_are_walked_not_just_the_first() -> None:
    """If a site has both, silently taking one would lose the other's sessions."""
    link = FakeLink(
        {
            "TDC Data": {
                "001_01-001 TDC Sessions": {APPLOG_DIR: {"001_01-001 Tdc.zip": 10}}
            },
            "TDC Sessions": {
                "001_01-002 TDC Sessions": {APPLOG_DIR: {"001_01-002 Tdc.zip": 20}}
            },
        }
    )
    plan = plan_site("001", ENTRY, "pw", _archive(), link=link)

    assert plan.remote_sessions == 2
    assert {f.name for f in plan.files} == {
        "001_01-001 Tdc.zip",
        "001_01-002 Tdc.zip",
    }
    assert any("2 session containers at root" in n for n in plan.notes)


def test_missing_tdc_data_is_an_error_for_a_normal_site() -> None:
    plan = plan_site("007", ENTRY, "pw", _archive(), link=FakeLink({"Other": {}}))
    assert plan.error is not None
    assert "TDC Data" in plan.error
    assert "TDC Sessions" in plan.error


def test_missing_container_error_says_what_the_root_holds() -> None:
    """The bare message sent me listing roots by hand across five sites."""
    link = FakeLink({"MR DICOM": {}, "PEDA Data": {}, "Misc": {}})
    plan = plan_site("007", ENTRY, "pw", _archive(), link=link)

    assert plan.error is not None
    assert "which holds" in plan.error
    for name in ("MR DICOM/", "PEDA Data/", "Misc/"):
        assert name in plan.error


def test_missing_tdc_data_is_expected_for_a_complaints_only_site() -> None:
    """23 sites are flagged this way; they must not read as failures."""
    entry = dict(ENTRY, status="Data for Complaints Only")
    plan = plan_site("126", entry, "pw", _archive(), link=FakeLink({"Other": {}}))

    assert plan.error is None
    assert any("expected: Data for Complaints Only" in n for n in plan.notes)


@pytest.mark.parametrize(
    "status",
    [
        # The landing page's own wording.
        "Data for Complaints Only",
        "Site Created, No Data Received",
        # Plausible hand-transcriptions of the same thing. status is typed by a
        # human into a gitignored file, so wording must not decide correctness.
        "Complaint Data Only",
        "complaints only",
        "DATA FOR COMPLAINTS ONLY",
        "no data received",
        "No data yet",
    ],
)
def test_status_wording_does_not_decide_correctness(status: str) -> None:
    plan = plan_site(
        "126", dict(ENTRY, status=status), "pw", _archive(), link=FakeLink({"Other": {}})
    )
    assert plan.error is None, f"{status!r} read as a failure"
    assert any("expected" in n for n in plan.notes)


@pytest.mark.parametrize("status", ["", "Active", "Data Available for AI"])
def test_a_normal_site_still_errors_on_a_missing_container(status: str) -> None:
    """The forgiving match must not swallow a genuine misconfiguration."""
    plan = plan_site(
        "126", dict(ENTRY, status=status), "pw", _archive(), link=FakeLink({"Other": {}})
    )
    assert plan.error is not None, f"{status!r} wrongly treated as no-data-expected"


def test_planner_never_raises() -> None:
    """A broken link must land on the plan, so one bad site cannot kill the run."""

    class Broken:
        root_sync_id = 0

        def find(self, *_):
            raise ConnectionError("boom")

        def listdir(self, *_):
            raise ConnectionError("boom")

    plan = plan_site("007", ENTRY, "pw", _archive(), link=Broken())
    assert plan.error == "ConnectionError: boom"
