# Project: Site Timing Analysis
# File: testing/tests/test_site_availability.py
# Primary author: Nicholas J. Sisco, Ph.D.
# Organization: Profound Medical, LLC
# Created: 2026-08-11
# Purpose: Tests read-only Sync.com and local Teams site inventory and parity behavior.
#
# Provenance: Original implementation or material contribution by
# Nicholas J. Sisco, Ph.D. for Profound Medical, LLC.
#
# Rights status: Proprietary / internal use unless otherwise specified
# by Profound Medical, LLC.
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path

import pytest

from site_timing_analysis import site_availability
from site_timing_analysis.site_availability import (
    ArtifactReference,
    _database_status,
    build_site_report,
    check_site_availability,
    inventory_local_site,
    inventory_remote_site,
    write_json_report,
)
from site_timing_analysis.single_case_acquisition import AcquisitionConfigurationError


@dataclass
class FakeItem:
    sync_id: int
    name: str
    is_dir: bool
    size: int = 0


class FakeSession:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


class FakeLink:
    root_sync_id = 0

    def __init__(
        self,
        children: dict[int, list[FakeItem]],
        *,
        fail_ids: set[int] | None = None,
        open_error: Exception | None = None,
    ) -> None:
        self.children = children
        self.fail_ids = fail_ids or set()
        self.open_error = open_error
        self.listdir_calls: list[int] = []
        self.session = FakeSession()

    def open(self) -> FakeLink:
        if self.open_error is not None:
            raise self.open_error
        return self

    def listdir(self, sync_id: int) -> list[FakeItem]:
        self.listdir_calls.append(sync_id)
        if sync_id in self.fail_ids:
            raise RuntimeError("https://signed.example/path?pltoken=DO-NOT-REPORT")
        return list(self.children.get(sync_id, []))


def _factory(link: FakeLink):
    def build(_url: str, _password: str) -> FakeLink:
        return link

    return build


def _write_sites(path: Path, sites: dict[str, dict] | None = None) -> Path:
    payload = sites or {
        "122": {
            "short_name": "ASUI",
            "url": "https://ln5.sync.com/dl/EXAMPLE00/aaaaaaaa-bbbbbbbb-cccccccc-dddddddd",
        }
    }
    path.write_text(json.dumps({"sites": payload}), encoding="utf-8")
    return path


def _remote_tree(case_ids: list[str]) -> dict[int, list[FakeItem]]:
    tree: dict[int, list[FakeItem]] = {0: [FakeItem(10, "TDC Sessions", True)]}
    case_folders: list[FakeItem] = []
    for index, case_id in enumerate(case_ids, start=1):
        case_folder_id = 100 + index
        applog_id = 200 + index
        session_folder_id = 300 + index
        database_id = 400 + index
        case_folders.append(
            FakeItem(case_folder_id, f"{case_id} TDC Sessions", True)
        )
        tree[case_folder_id] = [
            FakeItem(applog_id, "applog", True),
            FakeItem(
                session_folder_id,
                f"_2026-08-{index:02d}--10-00-00 {900000 + index}",
                True,
            ),
        ]
        tree[applog_id] = [FakeItem(500 + index, "should-not-be-seen", False)]
        tree[session_folder_id] = [FakeItem(database_id, "local.db", False, 1024)]
    tree[10] = case_folders
    return tree


def _create_local_site(
    root: Path,
    case_ids: list[str],
    *,
    with_database: set[str] | None = None,
) -> Path:
    site_path = root / "Clinical Science Team - ASUI_122"
    site_path.mkdir(parents=True)
    database_cases = set(case_ids) if with_database is None else with_database
    for case_id in case_ids:
        case_path = site_path / case_id
        case_path.mkdir()
        if case_id in database_cases:
            (case_path / "local.db").write_bytes(b"inventory-only-test")
    return site_path


def _check(
    *,
    tmp_path: Path,
    link: FakeLink,
    local_root: Path,
):
    return check_site_availability(
        site="122",
        sites_file=_write_sites(tmp_path / "sites.json"),
        local_root=local_root,
        sync_link_class=_factory(link),
        credential_loader=lambda: "not-reported",
    )


def test_complete_parity_is_read_only_and_does_not_traverse_applog(
    tmp_path: Path,
) -> None:
    case_ids = ["122_01-001", "122_01-002"]
    link = FakeLink(_remote_tree(case_ids))
    local_root = tmp_path / "Profound Medical"
    site_path = _create_local_site(local_root, case_ids)
    before = {
        path.relative_to(site_path): (path.read_bytes(), path.stat().st_mtime_ns)
        for path in site_path.rglob("local.db")
    }

    report = _check(tmp_path=tmp_path, link=link, local_root=local_root)

    after = {
        path.relative_to(site_path): (path.read_bytes(), path.stat().st_mtime_ns)
        for path in site_path.rglob("local.db")
    }
    assert report.status == "complete"
    assert report.exit_code == 0
    assert report.parity["matched_cases"] == case_ids
    assert report.parity["complete_cases"] == case_ids
    assert before == after
    assert 201 not in link.listdir_calls
    assert 202 not in link.listdir_calls
    assert link.session.closed


@pytest.mark.parametrize(
    ("roots", "reason_code"),
    [
        ([], "missing_recognized_remote_root"),
        (
            [
                FakeItem(10, "TDC Sessions", True),
                FakeItem(11, "TDC Data", True),
            ],
            "ambiguous_remote_roots",
        ),
    ],
)
def test_remote_requires_exactly_one_recognized_root(
    roots: list[FakeItem],
    reason_code: str,
) -> None:
    endpoint = inventory_remote_site(FakeLink({0: roots}), "122")

    assert endpoint.status == "failure"
    assert endpoint.reason_code == reason_code


def test_tdc_data_is_a_valid_single_remote_root() -> None:
    tree = _remote_tree(["122_01-001"])
    tree[0][0].name = "TDC Data"

    endpoint = inventory_remote_site(FakeLink(tree), "122")

    assert endpoint.status == "available"
    assert endpoint.recognized_root == "TDC Data"
    assert endpoint.cases[0].status == "available"


def test_remote_inventory_does_not_descend_below_session_children() -> None:
    tree = _remote_tree(["122_01-001"])
    tree[301] = [FakeItem(700, "nested", True)]
    tree[700] = [FakeItem(701, "local.db", False, 1024)]
    link = FakeLink(tree)

    endpoint = inventory_remote_site(link, "122")

    assert endpoint.cases[0].status == "missing_database"
    assert 700 not in link.listdir_calls


def test_remote_case_database_issues_are_distinct() -> None:
    tree = _remote_tree(["122_01-001", "122_01-002", "122_01-003"])
    tree[302] = []
    tree[303] = [
        FakeItem(403, "local.db", False, 1024),
        FakeItem(404, "LOCAL.DB", False, 1024),
    ]
    endpoint = inventory_remote_site(FakeLink(tree), "122")
    statuses = {case.case_id: case.status for case in endpoint.cases}

    assert statuses == {
        "122_01-001": "available",
        "122_01-002": "missing_database",
        "122_01-003": "ambiguous_database",
    }


def test_duplicate_remote_case_id_is_reported_without_descending() -> None:
    tree = _remote_tree(["122_01-001"])
    tree[10].append(FakeItem(999, "122_01-001 TDC Sessions", True))
    endpoint = inventory_remote_site(FakeLink(tree), "122")

    assert endpoint.duplicate_case_ids == ["122_01-001"]
    assert endpoint.cases[0].status == "duplicate_case_id"


def test_local_missing_site_uses_exact_teams_guidance(tmp_path: Path) -> None:
    root = tmp_path / "Profound Medical"
    root.mkdir()

    endpoint = inventory_local_site(root, "122")

    assert endpoint.reason_code == "local_site_missing"
    assert endpoint.reason == (
        "Site 122 is not available locally. Sync the site directory ending in "
        "_122 from the Clinical Science Team through the Teams app, then rerun."
    )


def test_ambiguous_local_site_directories_are_an_endpoint_failure(
    tmp_path: Path,
) -> None:
    root = tmp_path / "Profound Medical"
    (root / "Clinical Science Team - ASUI_122").mkdir(parents=True)
    (root / "Clinical Science Team - OTHER_122").mkdir()

    endpoint = inventory_local_site(root, "122")

    assert endpoint.status == "failure"
    assert endpoint.reason_code == "ambiguous_local_site_directories"
    assert len(endpoint.warnings) == 2


def test_local_missing_empty_and_duplicate_database_classification(
    tmp_path: Path,
) -> None:
    root = tmp_path / "Profound Medical"
    _create_local_site(
        root,
        ["122_01-001", "122_01-002"],
        with_database={"122_01-002"},
    )
    endpoint = inventory_local_site(root, "122")
    statuses = {case.case_id: case.status for case in endpoint.cases}

    assert statuses["122_01-001"] == "missing_database"
    assert statuses["122_01-002"] == "available"
    assert _database_status(
        [ArtifactReference("one/local.db", 1), ArtifactReference("two/LOCAL.DB", 1)],
        duplicate_status="duplicate_database",
    ) == "duplicate_database"
    assert _database_status(
        [ArtifactReference("one/local.db", 0)],
        duplicate_status="duplicate_database",
    ) == "empty_database"


def test_remote_only_local_only_and_case_issues_produce_exit_one(
    tmp_path: Path,
) -> None:
    tree = _remote_tree(["122_01-001", "122_01-002"])
    tree[302] = []
    link = FakeLink(tree)
    local_root = tmp_path / "Profound Medical"
    _create_local_site(
        local_root,
        ["122_01-001", "122_01-003", "122_01-004"],
        with_database={"122_01-001", "122_01-003"},
    )

    report = _check(tmp_path=tmp_path, link=link, local_root=local_root)

    assert report.exit_code == 1
    assert report.status == "differences"
    assert report.parity["remote_only_cases"] == ["122_01-002"]
    assert report.parity["local_only_cases"] == ["122_01-003", "122_01-004"]
    assert report.parity["remote_case_issues"] == {
        "122_01-002": "missing_database"
    }
    assert report.parity["local_case_issues"] == {
        "122_01-004": "missing_database"
    }


def test_noncanonical_folders_are_reported_but_excluded_from_clean_parity(
    tmp_path: Path,
) -> None:
    tree = _remote_tree(["122_01-001"])
    tree[10].append(FakeItem(999, "STA_01-001 TDC Sessions", True))
    local_root = tmp_path / "Profound Medical"
    site_path = _create_local_site(local_root, ["122_01-001"])
    (site_path / "STA_01-001").mkdir()

    report = _check(tmp_path=tmp_path, link=FakeLink(tree), local_root=local_root)

    assert report.exit_code == 0
    assert report.remote.noncanonical_folders == ["STA_01-001 TDC Sessions"]
    assert report.local.noncanonical_folders == ["STA_01-001"]
    assert report.remote.counts()["discovered_folders"] == (
        report.remote.counts()["canonical_case_folders"]
        + report.remote.counts()["noncanonical_folders"]
    )


def test_missing_sync_site_is_configuration_exit_two(tmp_path: Path) -> None:
    sites_file = _write_sites(
        tmp_path / "sites.json",
        {"064": {"url": "https://ln5.sync.com/dl/EXAMPLE00/key"}},
    )
    local_root = tmp_path / "Profound Medical"
    _create_local_site(local_root, ["122_01-001"])

    report = check_site_availability(
        site="122",
        sites_file=sites_file,
        local_root=local_root,
        sync_link_class=lambda _url, _password: None,
        credential_loader=lambda: "unused",
    )

    assert report.exit_code == 2
    assert report.remote.reason_code == "remote_configuration_failed"


def test_authentication_failure_is_sanitized_and_closes_session(
    tmp_path: Path,
) -> None:
    local_root = tmp_path / "Profound Medical"
    _create_local_site(local_root, ["122_01-001"])
    link = FakeLink(
        {},
        open_error=RuntimeError(
            "wrong password hunter2 https://sync.example/path?pltoken=SECRET"
        ),
    )

    report = _check(tmp_path=tmp_path, link=link, local_root=local_root)
    serialized = json.dumps(report.to_dict())

    assert report.exit_code == 2
    assert report.remote.reason_code == "remote_authentication_failed"
    assert "hunter2" not in serialized
    assert "pltoken" not in serialized.casefold()
    assert "https://" not in serialized.casefold()
    assert link.session.closed


def test_remote_subfolder_access_failure_is_exit_two_without_error_text(
    tmp_path: Path,
) -> None:
    tree = _remote_tree(["122_01-001"])
    link = FakeLink(tree, fail_ids={301})
    local_root = tmp_path / "Profound Medical"
    _create_local_site(local_root, ["122_01-001"])

    report = _check(tmp_path=tmp_path, link=link, local_root=local_root)
    serialized = json.dumps(report.to_dict())

    assert report.exit_code == 2
    assert report.remote.reason_code == "remote_listing_incomplete"
    assert "signed.example" not in serialized
    assert "DO-NOT-REPORT" not in serialized


def test_cli_console_and_json_agree_and_missing_local_guidance_is_printed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    link = FakeLink(_remote_tree(["122_01-001"]))
    monkeypatch.setattr(
        site_availability,
        "_load_sync_client",
        lambda _root, _zip: (_factory(link), lambda: "not-reported", lambda _: None),
    )
    sites_file = _write_sites(tmp_path / "sites.json")
    local_root = tmp_path / "Profound Medical"
    local_root.mkdir()
    report_path = tmp_path / "reports" / "site_122.json"

    exit_code = site_availability.main(
        [
            "--site",
            "122",
            "--sites-file",
            str(sites_file),
            "--local-root",
            str(local_root),
            "--report-json",
            str(report_path),
        ]
    )
    output = capsys.readouterr().out
    payload = json.loads(report_path.read_text(encoding="utf-8"))

    assert exit_code == payload["exit_code"] == 2
    assert payload["status"] == "failure"
    assert "Site 122 is not available locally. Sync the site directory ending in " in output
    assert "matched=0" in output
    assert "Result: failure; exit code=2" in output


def test_json_report_cannot_be_written_inside_local_parent(tmp_path: Path) -> None:
    local_root = tmp_path / "Profound Medical"
    _create_local_site(local_root, ["122_01-001"])
    report = _check(
        tmp_path=tmp_path,
        link=FakeLink(_remote_tree(["122_01-001"])),
        local_root=local_root,
    )

    with pytest.raises(AcquisitionConfigurationError):
        write_json_report(
            report,
            local_root / "site_122_report.json",
            local_root=local_root,
        )


def test_build_report_exit_two_for_root_ambiguity(tmp_path: Path) -> None:
    remote = inventory_remote_site(
        FakeLink(
            {
                0: [
                    FakeItem(10, "TDC Sessions", True),
                    FakeItem(11, "TDC Data", True),
                ]
            }
        ),
        "122",
    )
    local_root = tmp_path / "Profound Medical"
    _create_local_site(local_root, ["122_01-001"])
    local = inventory_local_site(local_root, "122")

    report = build_site_report(
        "122",
        remote,
        local,
        started_at_utc="2026-08-11T00:00:00+00:00",
    )

    assert report.exit_code == 2
    assert report.failure_reasons == ["remote:ambiguous_remote_roots"]
