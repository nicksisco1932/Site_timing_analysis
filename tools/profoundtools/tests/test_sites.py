"""Site configuration integrity.

The example file is always checked. The real sites.json is gitignored, so its
tests skip when absent (fresh clone, CI) and run on a working machine -- where a
transcription slip is exactly what we want to catch.
"""

from __future__ import annotations

import json
import os

import pytest

from sync_tdc_logs.sites import DEFAULT_SITES, EXAMPLE_SITES, SitesError, load_sites
from sync_tdc_logs.synclink import SyncLink

real_config = pytest.mark.skipif(
    not os.path.exists(DEFAULT_SITES),
    reason="sites.json is not committed; nothing to validate",
)


def test_example_file_exists_and_parses() -> None:
    with open(EXAMPLE_SITES, encoding="utf-8") as handle:
        config = json.load(handle)
    assert "sites" in config


def test_example_documents_the_skipped_site() -> None:
    """004 has no sync.com link; the example must show that shape."""
    sites = load_sites(EXAMPLE_SITES, None)
    assert "004" not in sites, "sites with an empty url must be filtered out"
    assert "007" in sites


def test_missing_config_gives_an_actionable_error() -> None:
    with pytest.raises(SitesError) as excinfo:
        load_sites(os.path.join(os.path.dirname(EXAMPLE_SITES), "nope.json"), None)
    assert "sites.example.json" in str(excinfo.value)


def test_wanted_filter() -> None:
    assert set(load_sites(EXAMPLE_SITES, "007")) == {"007"}
    assert set(load_sites(EXAMPLE_SITES, "007,059")) == {"007", "059"}


def test_unknown_site_is_filtered_not_fatal() -> None:
    assert load_sites(EXAMPLE_SITES, "999") == {}


@real_config
def test_every_configured_link_parses() -> None:
    for site, entry in load_sites(DEFAULT_SITES, None).items():
        link = SyncLink(entry["url"], "dummy")
        assert link.host.endswith("sync.com"), f"{site}: odd host {link.host}"
        assert len(link.link_key.split("-")) == 4, f"{site}: odd key {link.link_key}"


@real_config
def test_no_two_sites_share_a_link_id() -> None:
    """A duplicated link id means a copy/paste slip while transcribing the page."""
    seen: dict[str, str] = {}
    for site, entry in load_sites(DEFAULT_SITES, None).items():
        link_id = SyncLink(entry["url"], "dummy").link_id
        assert link_id not in seen, (
            f"sites {seen[link_id]} and {site} share link id {link_id}"
        )
        seen[link_id] = site


@real_config
def test_every_site_has_a_clinic_name() -> None:
    for site, entry in load_sites(DEFAULT_SITES, None).items():
        assert entry.get("clinic"), f"{site}: no clinic name"
