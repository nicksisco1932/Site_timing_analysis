"""Decide what is actually missing, spending as little sync.com traffic as possible.

Traffic discipline
------------------
The plan decides from the remote *session folder name* alone whether we already
hold a session, and only walks into ``applog`` for the gaps. Cost per site is
``2 + 2 x (missing sessions)`` API calls rather than one call per session.

The folder name is only a hint
------------------------------
**The folder name gets the first word; the file inside gets the last.** Sapporo
(site 007) has session folders whose numbering disagrees with the zips they
contain -- folder ``007_01-065`` holds ``007_01-064 ...``, folder ``007_01-076``
holds ``007_01-079 ...``. Joining on the folder name alone flagged seven
already-held files as missing: a 315 MB no-op download.

So once ``applog`` is listed -- already paid for -- every candidate is re-checked
against the archive by its own name plus an exact-filename match. Anything that
proves to be held is reported, never silently dropped.

Neither is the container name
-----------------------------
The folder holding the session folders is called ``TDC Sessions`` at most sites
and ``TDC Data`` at 007 and 119. Both are accepted. Whenever a lookup by a fixed
remote name fails, the note says what the folder *does* hold -- guessing the
layout from one site's screenshots is what produced 39 spurious errors.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sync_tdc_logs.archive import Archive
from sync_tdc_logs.sessions import session_key
from sync_tdc_logs.synclink import Item, SyncLink, SyncLinkError

# The folder holding the per-session folders. Sites disagree on its name: most
# call it "TDC Sessions", 007 and 119 call it "TDC Data", and 003/006/019 call it
# "TDC Session" (singular). Assuming "TDC Data" made 39 of 65 sites read as
# errors. A site may in principle have more than one, so all matches are walked
# rather than the first one winning.
SESSION_ROOT_DIRS = ("TDC Data", "TDC Sessions", "TDC Session")
TDC_DATA_DIR = SESSION_ROOT_DIRS[0]  # back-compat for callers/tests
APPLOG_DIR = "applog"

# A site's `status` in sites.json is transcribed by hand from the landing page's
# prose, so matching it must not hinge on the exact wording. Case-insensitive
# substrings, and "complaint" singular, so "Complaint Data Only" and "no data
# received" work as well as the page's own "Data for Complaints Only". Getting
# this wrong is silent and expensive: 23 sites flip from an expected note to a
# hard error, which is indistinguishable from the tool being broken.
NO_DATA_MARKERS = ("complaint", "no data")


@dataclass
class PlannedFile:
    site: str
    session: str
    name: str
    size: int
    sync_id: int
    cachekey: str
    enc_data_key: str
    enc_share_name: str
    remote_path: str
    # Needed by the pathdata call that supplies the download key. The listing
    # returns enc_data_key empty, so a plan without these cannot be fetched --
    # the server answers "getShardValue(DataKey) is empty".
    share_id: str = ""
    blob_id: int = 0


@dataclass
class SitePlan:
    site: str
    url: str
    clinic: str = ""
    status: str = ""
    remote_sessions: int = 0
    already_held: int = 0
    missing: list[str] = field(default_factory=list)
    files: list[PlannedFile] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    # Files whose folder name suggested a gap but whose own name proved they are
    # already held. Kept in the report so the mismatch stays visible.
    skipped: list[str] = field(default_factory=list)
    error: str | None = None

    @property
    def total_bytes(self) -> int:
        return sum(f.size for f in self.files)


def brief(items: list[Item], limit: int = 6) -> str:
    """One-line inventory of a remote folder, for plan notes."""
    if not items:
        return "nothing"
    shown = ", ".join(f"{i.name}{'/' if i.is_dir else ''}" for i in items[:limit])
    extra = len(items) - limit
    return f"{shown} (+{extra} more)" if extra > 0 else shown


def plan_site(
    site: str,
    entry: dict,
    password: str,
    archive: Archive,
    link: SyncLink | None = None,
) -> SitePlan:
    """Work out what is missing for one site. Never raises: errors land on the plan.

    ``link`` is injectable so the planning logic can be tested without network.
    """
    url = entry["url"]
    status = entry.get("status", "")
    plan = SitePlan(site=site, url=url, clinic=entry.get("clinic", ""), status=status)

    # The landing page flags sites that only ever sent complaint logs, or that
    # were provisioned but never sent data. For those, an absent "TDC Data"
    # folder is the documented state, not a failure.
    no_data_expected = any(m in status.casefold() for m in NO_DATA_MARKERS)

    try:
        if link is None:
            link = SyncLink(url, password).open()

        # List the root once and match in Python: link.find() would list it too
        # and then discard the siblings, and those siblings are exactly what we
        # need to report when no container matches.
        root_items = link.listdir(link.root_sync_id)
        wanted = {name.casefold() for name in SESSION_ROOT_DIRS}
        containers = [
            i for i in root_items if i.is_dir and i.name.strip().casefold() in wanted
        ]
        if not containers:
            names = " or ".join(repr(n) for n in SESSION_ROOT_DIRS)
            message = f"no {names} folder at link root, which holds {brief(root_items)}"
            if no_data_expected:
                plan.notes.append(f"{message} (expected: {status})")
            else:
                plan.error = message
            return plan
        if len(containers) > 1:
            plan.notes.append(
                f"{len(containers)} session containers at root "
                f"({', '.join(c.name for c in containers)}); walking all"
            )

        sessions = [
            (container, item)
            for container in containers
            for item in link.listdir(container.sync_id)
            if item.is_dir
        ]
        plan.remote_sessions = len(sessions)

        for container, folder in sessions:
            key = session_key(folder.name)
            if key is None:
                # e.g. the TDC 2.9-era "007_2.9_Session 001" folders, which carry
                # no session number to join on.
                plan.notes.append(f"unparsed session folder: {folder.name!r}")
                continue
            if archive.holds_session(key):
                plan.already_held += 1
                continue

            plan.missing.append(key)

            # Only now do we spend API calls on this session. List the session
            # folder once and search it in Python: link.find() would list it too,
            # then throw the siblings away, and those siblings are exactly what
            # we want to report if applog turns out to be empty.
            session_items = link.listdir(folder.sync_id)
            applog = next(
                (i for i in session_items if i.name.strip().lower() == APPLOG_DIR),
                None,
            )
            contents = link.listdir(applog.sync_id) if applog else []
            zips = [
                i for i in contents if not i.is_dir and i.name.lower().endswith(".zip")
            ]

            if not zips:
                # Three very different problems; say which, and always say what
                # the session folder holds so a stray log location shows up.
                if applog is None:
                    reason = f"no {APPLOG_DIR!r} folder"
                elif not contents:
                    reason = f"{APPLOG_DIR} is empty"
                else:
                    reason = f"no .zip in {APPLOG_DIR}, which holds {brief(contents)}"
                plan.notes.append(
                    f"{key}: {reason}; session folder holds {brief(session_items)}"
                )
                continue

            if len(zips) > 1:
                plan.notes.append(
                    f"{key}: {len(zips)} zips in {APPLOG_DIR} "
                    f"({', '.join(z.name for z in zips)})"
                )

            for item in zips:
                file_key = session_key(item.name)
                if archive.holds_filename(item.name):
                    plan.skipped.append(f"{item.name} (exact filename already held)")
                    continue
                if file_key and file_key != key and archive.holds_session(file_key):
                    plan.skipped.append(
                        f"{item.name} (folder said {key}, file says {file_key} "
                        f"-- already held)"
                    )
                    continue

                plan.files.append(
                    PlannedFile(
                        site=site,
                        session=file_key or key,
                        name=item.name,
                        size=item.size,
                        sync_id=item.sync_id,
                        cachekey=item.cachekey,
                        enc_data_key=item.enc_data_key,
                        enc_share_name=item.enc_share_name,
                        remote_path=(
                            f"{container.name}/{folder.name}/{applog.name}/{item.name}"
                        ),
                        share_id=str(item.raw.get("share_id") or ""),
                        blob_id=int(item.raw.get("blob_id") or 0),
                    )
                )
    except SyncLinkError as exc:
        plan.error = str(exc)
    except Exception as exc:  # noqa: BLE001 - one bad site must not kill the run
        plan.error = f"{type(exc).__name__}: {exc}"
    return plan
