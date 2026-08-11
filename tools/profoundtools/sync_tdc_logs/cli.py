"""Command-line entry point for sync-tdc-logs. See README for usage."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict

from sync_tdc_logs import __version__

DEFAULT_DEST = os.path.join(os.getcwd(), "_staging")


# --------------------------------------------------------------------------- #
#  setup
# --------------------------------------------------------------------------- #


def _cmd_setup(args: argparse.Namespace) -> int:
    import getpass

    from sync_tdc_logs import credentials

    if args.forget:
        if credentials.forget():
            print("Stored sync.com link password removed.")
        else:
            print("No stored password to remove.")
        return 0

    print(
        "All site links on the Commercial Data Landing Page share one password.\n"
        "It will be stored in the OS keyring (Windows Credential Manager ->\n"
        "Generic Credentials), not in any file in this repo."
    )
    first = getpass.getpass("sync.com link password: ")
    if not first:
        print("Nothing entered; aborted.", file=sys.stderr)
        return 2
    second = getpass.getpass("Confirm: ")
    if first != second:
        print("Passwords did not match; nothing stored.", file=sys.stderr)
        return 2

    credentials.store(first)
    print(f"Stored under keyring service {credentials.SERVICE!r}.")
    print("Verify with:  sync-tdc-logs ls 007")
    return 0


# --------------------------------------------------------------------------- #
#  plan -- the default, and a dry run
# --------------------------------------------------------------------------- #


def _cmd_plan(args: argparse.Namespace) -> int:
    from sync_tdc_logs import credentials
    from sync_tdc_logs.archive import load_archive
    from sync_tdc_logs.download import human
    from sync_tdc_logs.planner import SitePlan, plan_site
    from sync_tdc_logs.sites import load_sites

    sites = load_sites(args.sites_file, args.sites)
    if not sites:
        print("No sites selected.", file=sys.stderr)
        return 2

    scope = f"{len(sites)} site(s)" if args.sites else f"ALL {len(sites)} sites"
    print(f"Planning {scope}, {args.jobs} in parallel.")
    print(f"Reading local archive: {args.local_root}")
    archive = load_archive(args.local_root)
    print(
        f"  {len(archive):,} distinct sessions, "
        f"{len(archive.filenames):,} files already held"
    )
    if archive.unparsed:
        # These cannot answer "do we hold this session", so each one is a
        # potential false gap. Say so rather than quietly under-counting.
        print(
            f"  {len(archive.unparsed):,} file(s) carry no parseable session id "
            f"and can only be matched by exact filename, e.g. "
            f"{archive.unparsed[0]!r}"
        )
    print()

    password = credentials.load()

    plans: list[SitePlan] = []
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        futures = [
            pool.submit(plan_site, site, entry, password, archive)
            for site, entry in sites.items()
        ]
        for future in as_completed(futures):
            plans.append(future.result())
    plans.sort(key=lambda p: p.site)

    total_files = 0
    total_bytes = 0
    errors = 0
    for plan in plans:
        header = f"=== Site {plan.site}"
        if plan.clinic:
            header += f" - {plan.clinic}"
        print(f"{header} ===")
        if plan.status:
            print(f"  [landing page: {plan.status}]")
        if plan.error:
            errors += 1
            print(f"  ERROR: {plan.error}\n")
            continue

        print(
            f"  remote sessions: {plan.remote_sessions}   "
            f"already held: {plan.already_held}   "
            f"missing: {len(plan.missing)}"
        )
        for entry in plan.files:
            print(f"    + {entry.session:<14} {human(entry.size):>10}  {entry.name}")
            total_files += 1
            total_bytes += entry.size
        for skip in plan.skipped:
            print(f"    = {skip}")
        for note in plan.notes:
            print(f"    ! {note}")
        print()

    print("=" * 60)
    # With ~65 sites the per-site detail scrolls away, so roll it up.
    pending = [p for p in plans if p.files]
    if len(plans) > 1:
        print("SUMMARY")
        for plan in pending:
            print(
                f"  {plan.site}  {len(plan.files):>3} file(s)  "
                f"{human(plan.total_bytes):>10}  {plan.clinic}"
            )
        if not pending:
            print("  no site has anything to download")
        quiet = len(plans) - len(pending) - errors
        print(
            f"  ({len(pending)} site(s) with gaps, {quiet} up to date, "
            f"{errors} in error)"
        )
        print("-" * 60)

    print(f"TO DOWNLOAD: {total_files} file(s), {human(total_bytes)}")
    print(f"Destination : {args.dest}")
    if errors:
        print(f"Sites in error: {errors}")
    print("DRY RUN - nothing downloaded.")

    if args.out:
        payload = {
            "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "local_root": args.local_root,
            "dest": args.dest,
            # Only the URL, never the password.
            "sites": {p.site: sites[p.site]["url"] for p in plans if not p.error},
            "plans": [asdict(p) for p in plans],
        }
        with open(args.out, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
        print(f"\nPlan written to {args.out}")
        print(f"Execute with:  sync-tdc-logs fetch --plan {args.out}")
    return 0


# --------------------------------------------------------------------------- #
#  fetch
# --------------------------------------------------------------------------- #


def _make_confirm(total_bytes: int) -> "object":
    """An interactive per-file prompt for `fetch`.

    Returns YES / NO / ALL / QUIT. EOF or Ctrl-C reads as QUIT: if we cannot ask,
    we do not download.
    """
    from sync_tdc_logs.download import ALL, NO, QUIT, YES, human

    def confirm(index: int, count: int, site: str, entry: dict, dest: str) -> str:
        print(
            f"\n  [{index}/{count}] {entry['name']}\n"
            f"      site {site}, session {entry['session']}, {human(entry['size'])}\n"
            f"      from {entry.get('remote_path', '?')}\n"
            f"      into {dest}"
        )
        while True:
            try:
                answer = input("      download? [y]es / [n]o / [a]ll / [q]uit: ")
            except (EOFError, KeyboardInterrupt):
                print()
                return QUIT
            choice = answer.strip().lower()
            if choice in ("y", "yes"):
                return YES
            if choice in ("n", "no", ""):
                return NO
            if choice in ("a", "all"):
                return ALL
            if choice in ("q", "quit"):
                return QUIT
            print("      please answer y, n, a or q.")

    return confirm


def _cmd_fetch(args: argparse.Namespace) -> int:
    from sync_tdc_logs import credentials
    from sync_tdc_logs.download import human, run

    with open(args.plan, encoding="utf-8") as handle:
        payload = json.load(handle)

    dest_root = args.dest or payload.get("dest") or DEFAULT_DEST
    site_urls = payload.get("sites", {})
    jobs = [
        (plan["site"], entry)
        for plan in payload["plans"]
        for entry in plan.get("files", [])
    ]
    if args.limit:
        jobs = jobs[: args.limit]

    if not jobs:
        print("Nothing to download.")
        return 0

    total = sum(entry["size"] for _, entry in jobs)
    print(f"{len(jobs)} file(s), {human(total)} -> {dest_root}")

    # Confirmation is the default. --yes turns it off, and only --yes may: with no
    # terminal to ask at, refuse rather than quietly downloading a gigabyte.
    confirm = None
    if not args.yes:
        if not sys.stdin.isatty():
            print(
                "Refusing to download without confirmation: this shell has no "
                "terminal to prompt at.\nRe-run interactively, or pass --yes to "
                "approve all "
                f"{len(jobs)} file(s) ({human(total)}) up front.",
                file=sys.stderr,
            )
            return 2
        confirm = _make_confirm(total)
        print("Confirming each file. Answer 'a' to approve the rest.")
    else:
        print(f"--yes given: approving all {len(jobs)} file(s) without prompting.")

    outcome = run(jobs, site_urls, dest_root, credentials.load(), confirm=confirm)

    print(
        f"\nDownloaded {outcome.downloaded} file(s), "
        f"{human(outcome.bytes_written)}. "
        f"{outcome.skipped} skipped, {outcome.declined} declined, "
        f"{outcome.failed} failure(s)."
    )
    if outcome.downloaded:
        print(f"Staged in {dest_root} -- review, then move into the archive.")
    return outcome.exit_code


# --------------------------------------------------------------------------- #
#  ls -- read-only browsing, for diagnosing surprises in the plan
# --------------------------------------------------------------------------- #


def _cmd_ls(args: argparse.Namespace) -> int:
    from sync_tdc_logs import credentials
    from sync_tdc_logs.download import human
    from sync_tdc_logs.sites import load_sites
    from sync_tdc_logs.synclink import SyncLink

    sites = load_sites(args.sites_file, args.site)
    if args.site not in sites:
        print(f"Unknown site: {args.site}", file=sys.stderr)
        return 2

    link = SyncLink(sites[args.site]["url"], credentials.load()).open()
    sync_id = link.root_sync_id
    walked: list[str] = []
    for part in [p for p in args.path.split("/") if p]:
        found = link.find(sync_id, part)
        if found is None:
            print(f"Not found: {part!r} under /{'/'.join(walked)}", file=sys.stderr)
            print("Available here:", file=sys.stderr)
            for item in link.listdir(sync_id):
                print(f"  {item.name}{'/' if item.is_dir else ''}", file=sys.stderr)
            return 1
        walked.append(found.name)
        sync_id = found.sync_id

    items = link.listdir(sync_id)
    print(f"/{'/'.join(walked)}  ({len(items)} item(s))\n")
    for item in items:
        kind = "dir " if item.is_dir else "file"
        size = "" if item.is_dir else human(item.size)
        print(f"  {kind} {size:>10}  {item.name}")
    return 0


# --------------------------------------------------------------------------- #
#  sites -- what is configured, and what the archive holds for each
# --------------------------------------------------------------------------- #


def _cmd_sites(args: argparse.Namespace) -> int:
    from sync_tdc_logs.archive import load_archive
    from sync_tdc_logs.sites import load_sites

    sites = load_sites(args.sites_file, None)
    archive = None
    if not args.no_archive:
        try:
            archive = load_archive(args.local_root)
        except OSError as exc:
            print(f"(archive unreachable: {exc})\n", file=sys.stderr)

    print(f"{'site':<6}{'held':>6}  {'status':<34}clinic")
    print("-" * 96)
    for site in sorted(sites):
        entry = sites[site]
        held = len(archive.sessions_for_site(site)) if archive else 0
        print(
            f"{site:<6}{held if archive else '?':>6}  "
            f"{entry.get('status', '')[:32]:<34}{entry.get('clinic', '')[:44]}"
        )
    print("-" * 96)
    print(f"{len(sites)} site(s) with a sync.com link")
    return 0


# --------------------------------------------------------------------------- #


def main(argv: list[str] | None = None) -> int:
    from sync_tdc_logs.archive import DEFAULT_LOCAL_ROOT
    from sync_tdc_logs.sites import DEFAULT_SITES

    parser = argparse.ArgumentParser(
        prog="sync-tdc-logs",
        description=(
            "Mirror missing TDC application logs from the per-site sync.com share "
            "links into the local AppLogs archive."
        ),
    )
    parser.add_argument(
        "--version", action="version", version=f"sync-tdc-logs {__version__}"
    )
    sub = parser.add_subparsers(dest="cmd")

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--sites-file", default=DEFAULT_SITES)

    archive_opt = argparse.ArgumentParser(add_help=False)
    archive_opt.add_argument("--local-root", default=DEFAULT_LOCAL_ROOT)

    p = sub.add_parser(
        "plan",
        parents=[common, archive_opt],
        help="Report what is missing and download nothing (default action).",
    )
    p.add_argument(
        "--sites",
        help="Comma-separated site ids, e.g. 007,008. Omit to plan ALL sites.",
    )
    p.add_argument("--dest", default=DEFAULT_DEST, help="Where a later fetch will write.")
    p.add_argument("--jobs", type=int, default=4, help="Sites planned in parallel.")
    p.add_argument("--out", help="Write the plan to this JSON file.")
    p.set_defaults(func=_cmd_plan)

    p = sub.add_parser(
        "fetch",
        parents=[common],
        help="Execute a saved plan, confirming each file (see --yes).",
    )
    p.add_argument("--plan", required=True, help="Plan JSON from `plan --out`.")
    p.add_argument("--dest", help="Override the plan's destination.")
    p.add_argument("--limit", type=int, help="Only the first N files (start with 1).")
    p.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help="Skip the per-file confirmation and download everything in the plan.",
    )
    p.set_defaults(func=_cmd_fetch)

    p = sub.add_parser("ls", parents=[common], help="List a remote folder (read-only).")
    p.add_argument("site", help="Site id, e.g. 007.")
    p.add_argument(
        "path",
        nargs="?",
        default="",
        help='Remote path, e.g. "TDC Data/007_01-101 TDC Sessions/applog".',
    )
    p.set_defaults(func=_cmd_ls)

    p = sub.add_parser(
        "sites", parents=[common, archive_opt], help="List configured sites."
    )
    p.add_argument(
        "--no-archive", action="store_true", help="Skip the archive coverage column."
    )
    p.set_defaults(func=_cmd_sites)

    p = sub.add_parser("setup", help="Store the link password in the OS keyring.")
    p.add_argument("--forget", action="store_true", help="Remove the stored password.")
    p.set_defaults(func=_cmd_setup)

    if argv is None:
        argv = sys.argv[1:]
    args = parser.parse_args(argv)
    if not getattr(args, "cmd", None):
        parser.print_help()
        return 2

    from sync_tdc_logs.sites import SitesError

    try:
        return args.func(args)
    except (RuntimeError, SitesError) as exc:
        print(f"{exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
