"""Session-key normalisation: the only join between remote shares and archive.

Every case below is a real name observed in the archive or on a share. The
regression cases are marked -- they cost a 315 MB no-op download the first time.
"""

from __future__ import annotations

import pytest

from sync_tdc_logs.sessions import session_key

CASES = {
    # Plain three-part ids, all four separator permutations.
    "007_01-001 Tdc.zip": "007_01-001",
    "007_01-002_Tdc.zip": "007_01-002",
    "007_01-100 Tdc.2025_06_10.zip": "007_01-100",
    "007_01-058_1 Tdc.2024_05_07.zip": "007_01-058",
    "007_01-079 Dup_Tdc.2024_10_30.zip": "007_01-079",
    "007_01-135 Tdc.2026_01_21.log.zip": "007_01-135",
    "001_01-109-Tdc.zip": "001_01-109",
    "017-01_058_Log_Tdc.2021_01_18_Complaint.zip": "017_01-058",
    "099-01-134-log-Tdc.2025_06_07.zip": "099_01-134",
    "105-01-012 Tdc.2026_02_27.zip": "105_01-012",
    "129-01_065_Tdc.2026_06_03_2.zip": "129_01-065",
    # Two-part ids (no system field) must stay two-part.
    "007-108 Tdc.2017_09_30_1.zip": "007-108",
    "007-101 Tdc.2017_05_27_1.zip": "007-101",
    # Remote folder forms.
    "114_01-005 TDC Sessions": "114_01-005",
    "007_01-001 TDC Sessions": "007_01-001",
    # Three-digit system field: rare (one file in the archive) but dropping it
    # makes site 109 session 002 look missing and re-downloads it.
    "109_001-002 Tdc.2024_07_11.zip": "109_001-002",
    # REGRESSION: these folder forms yielded the bogus key "007-01" when a single
    # permissive pattern let `system` swallow digits out of `session`.
    "007-01-145 TDC Sessions": "007_01-145",
    "007-01_145 TDC Sessions": "007_01-145",
    "007-01-145": "007_01-145",
    # No session number to join on.
    "Data_Clean": None,
    "007_2.9_Session 001": None,
    "": None,
}


@pytest.mark.parametrize("name,expected", sorted(CASES.items()))
def test_session_key(name: str, expected: str | None) -> None:
    assert session_key(name) == expected


def test_system_field_is_part_of_the_key() -> None:
    """007-108 and 007_01-108 are different sessions, not one."""
    assert session_key("007-108 Tdc.zip") != session_key("007_01-108 Tdc.zip")


def test_2017_and_2025_runs_do_not_collide() -> None:
    """The 2017 007-1xx run and the 2025 007_01-1xx run overlap numerically only.

    Merging them would silently hide 16 genuine gaps at Sapporo.
    """
    assert session_key("007-101 Tdc.2017_05_27_1.zip") != session_key(
        "007_01-101 Tdc.zip"
    )


@pytest.mark.parametrize(
    "folder,file",
    [
        ("007-01_145 TDC Sessions", "007_01-145 Tdc.2026_04_15.zip"),
        ("007-01-145 TDC Sessions", "007_01-145 Tdc.2026_04_16.zip"),
    ],
)
def test_separator_variants_agree_with_their_files(folder: str, file: str) -> None:
    """A folder that merely uses a different separator must parse to the file's key."""
    assert session_key(folder) == session_key(file)


@pytest.mark.parametrize(
    "name,expected",
    [
        # 111 archive files are named this way, and they hid 222 sessions.
        ("applog - 001_01-002_anonymized.zip", "001_01-002"),
        ("applog - 006_01-009_anonymized.zip", "006_01-009"),
        # Two separators, and a date before the id, but still the tail wins.
        ("Log.2019_01_15_07_52_31.txt - 002_01-026_anonymized.zip", "002_01-026"),
    ],
)
def test_id_after_a_separator_is_found(name: str, expected: str) -> None:
    assert session_key(name) == expected


@pytest.mark.parametrize(
    "name",
    [
        # The whole reason the tail match is separator-anchored rather than a free
        # search: this contains "024_08_20", which parses as site 024 / system 08
        # / session 20 -- a key for a site the filename never mentions. Minting it
        # would mask a genuine gap for site 024.
        "007_01-064 Tdc.2024_08_20.zip",
        "007_01-145 Tdc.2026_04_15_2nd.zip",
    ],
)
def test_a_date_never_leaks_into_the_key(name: str) -> None:
    key = session_key(name)
    assert key is not None
    assert key.startswith("007_01-"), f"date leaked into the key: {key}"


@pytest.mark.parametrize(
    "name",
    [
        # Old-era files keyed by a three-letter site code. No site mapping exists,
        # so these stay unparsed on purpose -- guessing a site id would be worse
        # than reporting them. Archive.unparsed keeps them visible.
        "cug-101 Tdc.2019_01_01.zip",
        "sun-014 Tdc.2018_03_12.zip",
        "Tdc.2019_02_02.zip",
    ],
)
def test_unmappable_names_stay_unparsed(name: str) -> None:
    assert session_key(name) is None


@pytest.mark.parametrize(
    "folder,file",
    [
        ("007_01-065 TDC Sessions", "007_01-064 Tdc.2024_08_20.zip"),
        ("007_01-076 TDC Sessions", "007_01-079 Tdc.2024_10_30.zip"),
    ],
)
def test_known_real_world_mislabelling(folder: str, file: str) -> None:
    """Sapporo folders whose number genuinely differs from the zip inside.

    No regex can reconcile these, which is why the planner re-checks the file's
    own name against the archive. If these ever agree, the test data is wrong.
    """
    assert session_key(folder) != session_key(file)
    assert session_key(file) is not None
