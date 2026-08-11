"""Normalise a TDC log filename or remote session folder into a session id.

This is the only stable join between the remote shares and the local archive, so
it carries the weight of the whole tool: a wrong key either re-downloads
something we already hold or hides a real gap.

Session ids come in two genuine flavours, and either separator gets used for
either join::

    007_01-100 / 007-01_145 / 007-01-145 / 109_001-002   -> site, system, session
    007-108                                             -> site, session

They are told apart by the **leading zero** on the system field. Verified against
all 3,486 entries of the archive: every three-part id has a zero-leading middle
field (``01`` x3038, ``001`` x1) and none is ambiguous.

Order matters, and a single permissive pattern will not do. Letting ``system``
match any digits lets it eat the front of ``session``, which is what turned the
folder ``007-01_145`` into the meaningless key ``007-01`` and made seven
already-held files look missing.
"""

from __future__ import annotations

import re

SESSION_PATTERNS = (
    re.compile(r"^(?P<site>\d{3})[_-](?P<system>0\d{0,2})[_-](?P<session>\d+)"),
    re.compile(r"^(?P<site>\d{3})-(?P<session>\d+)"),
)

# Some archive files carry the id *after* a " - " separator rather than at the
# front: "applog - 001_01-002_anonymized.zip", and even
# "Log.2019_01_15_07_52_31.txt - 002_01-026_anonymized.zip". 111 files are named
# this way, hiding 222 sessions from the index -- each one a session the planner
# would report missing and re-download.
TAIL_SEPARATOR = " - "


def _candidates(name: str) -> list[str]:
    """The substrings of ``name`` allowed to start a session id.

    Deliberately NOT a free regex search. ``007_01-064 Tdc.2024_08_20.zip``
    contains ``024_08_20``, which parses cleanly as site 024 / system 08 /
    session 20 -- a key for a site the filename never mentions. Searching
    anywhere would mint that key and mask a real gap for site 024, so only the
    string start and the text after a " - " separator are ever tried.
    """
    candidates = [name]
    if TAIL_SEPARATOR in name:
        candidates.append(name.rsplit(TAIL_SEPARATOR, 1)[1].strip())
    return candidates


def session_key(name: str) -> str | None:
    """Return the canonical session id for ``name``, or None if it has none.

    ``007-108`` and ``007_01-108`` are deliberately different keys, as are the
    2017 ``007-1xx`` run and the 2025 ``007_01-1xx`` run: they overlap
    numerically but are unrelated sessions, so the system stays in the key.
    """
    for candidate in _candidates(name.strip()):
        for pattern in SESSION_PATTERNS:
            match = pattern.match(candidate)
            if not match:
                continue
            groups = match.groupdict()
            site, session = groups["site"], groups["session"]
            system = groups.get("system")
            return f"{site}_{system}-{session}" if system else f"{site}-{session}"
    return None


def site_of(key: str) -> str:
    """The three-digit site id from a session key."""
    return key[:3]
