"""Inventory of the local log archive (a flat directory of zips)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from sync_tdc_logs.sessions import session_key

DEFAULT_LOCAL_ROOT = r"\\192.168.0.249\AppLogs"


@dataclass
class Archive:
    """What the archive already holds, indexed two ways.

    ``by_session`` answers "do we have this session at all", which is the cheap
    first-pass check. ``filenames`` answers "do we have this exact file", which
    is the backstop for sites whose folder numbering disagrees with the zips
    inside them.
    """

    root: str
    by_session: dict[str, list[str]] = field(default_factory=dict)
    filenames: set[str] = field(default_factory=set)
    # Files whose name carries no parseable session id. They are still matched by
    # exact filename, but they cannot answer "do we hold this session", so every
    # one is a session the planner may report missing. Never let this be silent:
    # 111 such files once hid 222 sessions.
    unparsed: list[str] = field(default_factory=list)

    def holds_session(self, key: str | None) -> bool:
        return bool(key) and key in self.by_session

    def holds_filename(self, name: str) -> bool:
        return name.casefold() in self.filenames

    def sessions_for_site(self, site: str) -> list[str]:
        return sorted(k for k in self.by_session if k.startswith(site))

    def __len__(self) -> int:
        return len(self.by_session)


def load_archive(root: str = DEFAULT_LOCAL_ROOT) -> Archive:
    """Scan ``root`` once, building both indexes.

    Entries beginning with ``@`` are NAS bookkeeping (@Recycle,
    @Recently-Snapshot) and are skipped.
    """
    archive = Archive(root=root)
    with os.scandir(root) as entries:
        for entry in entries:
            if entry.name.startswith("@"):
                continue
            archive.filenames.add(entry.name.casefold())
            key = session_key(entry.name)
            if key:
                archive.by_session.setdefault(key, []).append(entry.name)
            elif entry.is_file():
                archive.unparsed.append(entry.name)
    return archive
