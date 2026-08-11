"""The per-site share links, transcribed from the Commercial Data Landing Page.

``sites.json`` is not committed: a sync.com link URL contains the share's
decryption key. It is not sufficient for access on its own -- every API call is
rejected without the password -- but it does not belong in git history either.
``sites.example.json`` shows the shape.
"""

from __future__ import annotations

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(HERE)
DEFAULT_SITES = os.path.join(PROJECT_ROOT, "sites.json")
EXAMPLE_SITES = os.path.join(PROJECT_ROOT, "sites.example.json")


class SitesError(RuntimeError):
    """The site configuration is missing or unusable."""


def load_sites(path: str | None = None, wanted: str | None = None) -> dict[str, dict]:
    """Load ``site id -> {url, clinic, status, ...}``.

    Sites with no ``url`` are skipped: site 004 is listed on the landing page but
    its link points at a SharePoint site rather than a sync.com share.

    ``wanted`` is a comma-separated allow-list, e.g. ``"007,008"``.
    """
    path = path or DEFAULT_SITES
    if not os.path.exists(path):
        raise SitesError(
            f"No site configuration at {path}.\n"
            f"sites.json is deliberately not committed (link URLs embed the share "
            f"decryption key). Copy sites.example.json to sites.json and fill in "
            f"the links from the Commercial Data Landing Page."
        )
    with open(path, encoding="utf-8") as handle:
        config = json.load(handle)

    raw = config.get("sites", config)
    sites: dict[str, dict] = {}
    for site, entry in raw.items():
        if not isinstance(entry, dict):
            entry = {"url": entry}
        if not entry.get("url"):
            continue
        sites[site] = entry

    if wanted:
        keep = {s.strip() for s in wanted.split(",") if s.strip()}
        unknown = keep - sites.keys()
        if unknown:
            print(
                f"Unknown site(s): {', '.join(sorted(unknown))}",
                file=sys.stderr,
            )
        sites = {s: e for s, e in sites.items() if s in keep}
    return sites
