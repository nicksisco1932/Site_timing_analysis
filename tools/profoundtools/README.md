# sync-tdc-logs

Mirrors missing TDC application logs from the per-site **sync.com** share links
(the ones on the Commercial Data Landing Page) into the local archive at
`\\192.168.0.249\AppLogs`.

## Install

```bash
poetry install
```

Store the link password once — all site links share one:

```bash
poetry run sync-tdc-logs setup
```

It goes to the OS keyring (Windows Credential Manager → Generic Credentials),
never to a file in this repo. `SYNC_LINK_PASSWORD` overrides it for automation.

Then create `sites.json` — see [Site configuration](#site-configuration).

## Usage

Everything is a dry run until you explicitly `fetch`.

```bash
# ALL sites (omit --sites), download nothing
poetry run sync-tdc-logs plan --out plan.json

# one or two sites
poetry run sync-tdc-logs plan --sites 007,008 --out plan.json

# what is configured, and how much of it the archive already holds
poetry run sync-tdc-logs sites

# execute a saved plan -- confirms every file individually
poetry run sync-tdc-logs fetch --plan plan.json --limit 1
poetry run sync-tdc-logs fetch --plan plan.json

# approve the whole plan up front (needed for unattended runs)
poetry run sync-tdc-logs fetch --plan plan.json --yes

# browse a share read-only, to diagnose an odd plan note
poetry run sync-tdc-logs ls 007
poetry run sync-tdc-logs ls 007 "TDC Data/007_01-101 TDC Sessions/applog"
```

`plan` runs 4 sites in parallel (`--jobs`). Over many sites it prints a per-site
roll-up so the detail does not scroll away.

Downloads land in `_staging/` by default, **not** straight into the archive —
review, then move. Point `--dest` at the share to write directly.

## Confirmation

`fetch` asks about **every file** before downloading it:

```
  [3/16] 129_01-027 Tdc.2026_01_16.log.zip
      site 129, session 129_01-027, 64.5 MB
      from TDC Sessions/129_01-027 TDC Sessions/applog/129_01-027 Tdc.2026_01_16.log.zip
      into …\_staging
      download? [y]es / [n]o / [a]ll / [q]uit:
```

`n` is the default on a bare Enter, `a` approves everything remaining, `q` stops
and counts the rest as undecided. These are clinical logs, hundreds of MB each,
so the default is one deliberate decision per file rather than one per batch.

The question is asked **before** the link is opened, so declining a run costs no
network at all.

`--yes` skips the prompt. It is the only way to run unattended: with no terminal
to ask at, `fetch` refuses and exits 2 rather than quietly downloading a
gigabyte. Declining is a choice, not an error — it never sets a failure exit
code.

## Why a custom client

The sync.com links are end-to-end encrypted: folder and file names arrive
AES-GCM encrypted and are decrypted in the browser. There is no public API and
`rclone` has no sync.com backend, so `synclink.py` implements the read-only slice
of the web-app protocol. Its module docstring carries the derivation; the short
version:

| Step | Mechanism |
|---|---|
| Access token | `passwordlock` = SHA-1 hex of the link password |
| Share key | `PBKDF2-HMAC-SHA256(url_key, hex_salt, 10000, 64 B)` |
| Names (`1:`) | AES-256-GCM, key `sharekey[32:64]`, IV = first 12 B, 96-bit tag |
| Data keys (`2:`) | AES-256-GCM, key `sharekey[0:32]` |
| Download | data key RSA-PKCS1v1.5'd to sync.com's compat key, request signed by `linksignrequest`, streamed from a `servers_compat` host with `pltoken` |

The encryption key comes from the **URL key**, not the password — the password
only gates the API. Anyone with the full URL *and* the password can read.

Server-side decryption ("Link compatibility", `compat: 1`) is what makes a plain
HTTP download possible; without it we would have to reassemble and decrypt
128 KiB GCM chunks client-side.

## Traffic discipline

The archive is a flat pile of ~3 500 zips with inconsistent names
(`007_01-100 Tdc.zip`, `007_01-100 Tdc.2025_06_10.zip`, `007_01-107_Tdc.zip`,
`007-108 Tdc.2017_09_30_1.zip`). The only stable join key is the **session id**,
so the plan decides from the remote *session folder name* alone whether we
already hold it, and only walks into `applog` for gaps. Cost per site is
`2 + 2 x (missing sessions)` API calls rather than one per session.

### The container name varies by site

The folder holding the session folders has three spellings in the wild:

| Name | Sites |
|---|---|
| `TDC Sessions` | most |
| `TDC Data` | 007, 119 |
| `TDC Session` | 003, 006, 019 |

All three are accepted, and every match is walked — a site with two containers
must not silently lose one. Assuming `TDC Data` (inferred from site 007 alone)
made 39 of 65 sites report an error while site 001 sat there with 254 session
folders.

Below that level the layout is uniform: `<session> TDC Sessions/applog/*.zip`.

When a lookup by a fixed remote name fails, the note says what the folder *does*
hold. The old bare "not found" message meant listing five roots by hand to
discover why.

### Not every session has an applog

Of the sessions the archive lacks, most have an empty `applog/` or none at all.
38 instead hold a zip at the *session* level, next to `local.db` —
`001_01-167 2019-07-24--13-53-41.zip`. Those are session exports, not
application logs: no timestamp-named file appears anywhere in the 3,486-file
archive, whose every entry is an applog (`… Tdc.<date>.zip`, `applog.zip`,
`applog - …_anonymized.zip`). They are reported as notes and never downloaded.

### The folder name is only a hint

**The folder name gets the first word; the file inside gets the last.** Sapporo
has session folders whose numbering disagrees with the zips they contain — folder
`007_01-065` holds `007_01-064 …`, folder `007_01-076` holds `007_01-079 …`.
Joining on the folder name alone flagged seven already-held files as missing: a
315 MB no-op.

So once `applog` is listed (already paid for), each candidate is re-checked
against the archive by its **own** name, plus an exact-filename match. Anything
already held is reported with `=` rather than silently dropped, so the mismatch
stays visible.

### Session id shapes

Two genuine flavours, either separator for either join:

| Example | Reading |
|---|---|
| `007_01-100`, `007-01_145`, `007-01-145`, `109_001-002` | site / system / session |
| `007-108` | site / session |

Told apart by the **leading zero** on the system field — verified across all
3 486 archive entries: every three-part id has a zero-leading middle field
(`01` ×3038, `001` ×1) and none is ambiguous. Without that rule a single
permissive pattern lets `system` eat digits out of `session`, which turned folder
`007-01_145` into the meaningless key `007-01`.

`007-108` and `007_01-108` are deliberately **different** sessions, as are the
2017 `007-1xx` run and the 2025 `007_01-1xx` run — numerically overlapping but
unrelated, so the system stays in the key.

The id is also read after a `" - "` separator, because 111 archive files are
named `applog - 001_01-002_anonymized.zip` and one is
`Log.2019_01_15_07_52_31.txt - 002_01-026_anonymized.zip`. Missing them hid 222
sessions from the index — every one a session the planner would have reported
missing and re-downloaded.

That match is anchored to the separator and **never** a free search:
`007_01-064 Tdc.2024_08_20.zip` contains `024_08_20`, which parses cleanly as
site 024 / system 08 / session 20. Searching anywhere would mint a key for a site
the filename never mentions and mask a genuine gap for site 024.

### What the index still cannot key

178 files carry no parseable session id — the old three-letter-site-code era
(`CUG-034 Tdc.2024_03_16.zip`, plus `TUP-`, `LHS-`, `SUN-`, `FIN-`, `USW-`,
`STA-`, and 7 bare `Tdc.<date>.zip`). No code-to-site mapping exists here, and
guessing one would mark a real gap as held — the single failure mode that loses
data silently. They are matched by exact filename only, and `plan` prints the
count in its header so the shortfall is never invisible.

## Site configuration

`sites.json` is **not committed**: a sync.com link URL embeds the share's
decryption key, so the file is a credential. It is not sufficient for access on
its own — every API call is rejected without the password — but treat it like
one: do not paste a link into a ticket, chat, or commit.

**It is also the only copy.** Nothing in git can rebuild it. If you lose it, you
re-transcribe all ~65 entries from the **Commercial Data Landing Page** in
SharePoint: its *Quick links* web part gives one link per site, and the table
beside it gives `short_name`, `clinic` and the *Data Available for AI* column.
Worth keeping a copy somewhere backed up but not shared.

Copy `sites.example.json` to `sites.json` and fill it in. The shape:

```json
{
  "sites": {
    "007": {
      "short_name": "SHH",
      "clinic": "Sapporo Hokuyu Hospital",
      "data_for_ai": "No",
      "url": "https://ln5.sync.com/dl/<id>/<key>"
    }
  }
}
```

Only `url` is required; `clinic` is asserted by the tests, and `status` matters
for the sites below.

Three link shapes appear on the page and all are accepted:

| Shape | Note |
|---|---|
| `/dl/<id>/<key>` | current canonical form |
| `/dl/<id>#<key>` | older form — key was a fragment, read from `location.hash` |
| `/4.0/dl/<id>#<key>` | version-pinned variant |

Site **004** is listed but points at a SharePoint site rather than a sync.com
share, so it carries an empty `url` and is skipped.

`status` mirrors the caveats the page states in prose. 23 sites are *Data for
Complaints Only* and 1 is *Site Created, No Data Received*; for those an absent
session container is the documented state, so the planner reports a note rather
than an error.

Any `status` containing **`complaint`** or **`no data`** counts, case-insensitive
— so "Complaint Data Only" and "no data received" work as well as the page's own
wording. Getting this wrong used to be silent and expensive: those 23 sites flip
to hard errors, which looks identical to the tool being broken.

### Checking a config you just built

```bash
poetry run pytest            # every URL parses, no two sites share a link id
poetry run sync-tdc-logs sites   # all sites + how much of each the archive holds
poetry run sync-tdc-logs ls 007  # proves the password and one real link work
```

The duplicate-link-id assertion is the one that catches a copy/paste slip while
transcribing. **These tests skip when `sites.json` is absent**, so a green suite
does not mean the config exists — check `sites` output for the row count.

## Tests

```bash
poetry run pytest
```

No network and no password required. `tests/test_planner.py` drives the planner
against a fake share, including the duplicate trap above.

## Fragility

This tracks an undocumented private protocol reverse-engineered from web bundle
`cp-3.1.38`. A sync.com front-end update can break it without notice. The failure
mode is a clear exception — bad name decryption, or a non-200 on the signed
download URL — not silent corruption: downloads are size-checked against the
listing and written via `.part` then renamed.
