"""Execute a saved plan: stream each planned file to the destination.

Every file is confirmed individually before anything is fetched. These are
clinical logs pulled from an external service, hundreds of MB each, so the
default is one deliberate decision per file rather than one for the batch.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from typing import Callable

from sync_tdc_logs.synclink import Item, SyncLink

# What a confirm callback may return.
YES, NO, ALL, QUIT = "yes", "no", "all", "quit"

ConfirmFn = Callable[[int, int, str, dict, str], str]


@dataclass
class Outcome:
    downloaded: int = 0
    skipped: int = 0
    failed: int = 0
    declined: int = 0
    bytes_written: int = 0

    @property
    def exit_code(self) -> int:
        return 1 if self.failed else 0


def human(size: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:,.1f} {unit}"
        size /= 1024
    return ""


def run(
    jobs: list[tuple[str, dict]],
    site_urls: dict[str, str],
    dest_root: str,
    password: str,
    confirm: ConfirmFn | None = None,
) -> Outcome:
    """Download each ``(site, file-entry)`` job into ``dest_root``.

    ``confirm`` is asked about every file and returns ``YES``, ``NO``, ``ALL`` or
    ``QUIT``. Passing ``None`` approves everything -- that is the ``--yes`` path,
    and it must be an explicit choice by the caller, never a fallback.

    The question is asked *before* the link is opened, so declining a whole run
    costs no network at all. Links are then opened lazily and reused per site, so
    a run over one site costs a single ``open()``. A failure on one file is
    reported and the run continues.
    """
    outcome = Outcome()
    links: dict[str, SyncLink] = {}
    approve_rest = confirm is None
    os.makedirs(dest_root, exist_ok=True)

    for index, (site, entry) in enumerate(jobs, start=1):
        target = os.path.join(dest_root, entry["name"])
        if os.path.exists(target):
            print(f"  = {entry['name']} (already present in dest)")
            outcome.skipped += 1
            continue

        if not approve_rest:
            assert confirm is not None  # approve_rest is True when confirm is None
            answer = confirm(index, len(jobs), site, entry, dest_root)
            if answer == ALL:
                approve_rest = True
            elif answer == QUIT:
                # Everything not yet decided counts as declined, including this one.
                remaining = len(jobs) - index + 1
                outcome.declined += remaining
                print(f"  stopped; {remaining} file(s) left undecided")
                break
            elif answer != YES:
                outcome.declined += 1
                print(f"  - {entry['name']} (declined)")
                continue

        # share_id/blob_id feed the pathdata call that supplies the download key.
        # A plan saved before they were recorded cannot be fetched, and the
        # server's complaint for that case ("getShardValue(DataKey) is empty")
        # says nothing about the cause -- so check here, before opening anything,
        # and say what to do.
        if not entry.get("share_id") or not entry.get("blob_id"):
            outcome.failed += 1
            print(
                f"    FAILED: {entry['name']}: plan predates share_id/blob_id; "
                f"re-run `plan --out` to refresh it",
                file=sys.stderr,
            )
            continue

        print(
            f"  > [{index}/{len(jobs)}] {entry['name']} ({human(entry['size'])})",
            flush=True,
        )
        try:
            # Opening the link is inside the try: a bad URL or an unreachable
            # site must cost that file, not the rest of the batch.
            if site not in links:
                links[site] = SyncLink(site_urls[site], password).open()
            link = links[site]

            item = Item(
                sync_id=entry["sync_id"],
                name=entry["name"],
                is_dir=False,
                size=entry["size"],
                cachekey=entry["cachekey"],
                enc_data_key=entry["enc_data_key"],
                enc_share_name=entry["enc_share_name"],
                raw={"share_id": entry["share_id"], "blob_id": entry["blob_id"]},
            )
            written = link.download(item, target)
            outcome.downloaded += 1
            outcome.bytes_written += written
        except Exception as exc:  # noqa: BLE001 - keep going through the batch
            outcome.failed += 1
            print(f"    FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)

    return outcome
