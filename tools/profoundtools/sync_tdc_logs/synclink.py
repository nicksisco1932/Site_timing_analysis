"""Read-only client for password-protected sync.com public download links.

Implements just enough of the sync.com web-app protocol (engine cp-3.1.38,
``linkversion`` 2) to walk a shared folder tree and download files. Derived from
the public web bundle at https://ln5.sync.com/main.*.js.

Protocol summary
----------------
A link URL looks like ``https://ln5.sync.com/dl/<link_id>/<link_key>``.

* ``passwordlock`` -- SHA-1 hex digest of the link password. Sent with every API
  call; it is purely an access-control token. It is NOT part of the encryption.
* Share key -- ``PBKDF2-HMAC-SHA256(link_key, salt, iterations, 64 bytes)``,
  where ``salt`` (hex) and ``iterations`` come from the ``linkpathlist``
  response. The *URL key* is the key material, which is why anyone holding the
  full URL plus password can decrypt.
* File/folder names (``enc_share_name``, prefix ``1:``) -- AES-256-GCM with a
  96-bit tag, key = ``sharekey[32:64]``, IV = first 12 bytes of the blob.
* Per-file data keys (``enc_data_key``, prefix ``2:``) -- same construction but
  key = ``sharekey[0:32]``.
* Download -- the plaintext data key is RSA-PKCS1v1.5 encrypted to a hardcoded
  sync.com "compat" public key, bundled into a request dict, and signed by the
  server via ``linksignrequest``. The signed dict becomes the query string of a
  ``/p/<filename>`` URL on a ``servers_compat`` host, which streams the file
  already decrypted. This is the "Link compatibility" feature; it requires
  ``compat: 1`` on the link.
"""

from __future__ import annotations

import base64
import hashlib
import mimetypes
import os
import re
import time
import urllib.parse
from dataclasses import dataclass, field
from typing import Any, Iterable

import requests
from cryptography.hazmat.primitives import hashes  # noqa: F401  (kept for clarity)
from cryptography.hazmat.primitives.asymmetric import padding as asym_padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.serialization import load_pem_public_key

ENGINE = "cp-3.1.38"
DOWNLOAD_ENGINE = "ln-3.1.38"

# Browser UA. The server hashes this into the signed request, so it only has to
# be stable between linksignrequest and the download GET.
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
)

# sync.com production "compat" RSA public key, lifted verbatim from the web
# bundle (syncCryptService.compatDatakeyEncrypt). The compat download server
# decrypts the per-file data key with the matching private key.
COMPAT_PUBKEY_PEM = """-----BEGIN PUBLIC KEY-----
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAsRA0ObSDjWc1ErNAQeN5
9WJLFNTBLHP5pGsDnRNXJfX0GkGB/PRV3vTv7OOUllZgy2J4sSnc/lZit50DcuNk
TAFU3BvNxh2qJfdVxhzdSPRw2hFnnEz4rN9+VuCbEcz4QGiVX2j3jqZLJyioJr5Q
ei+UeAcOnjHBP47H2On4sMdDyec2pSjTCsh0ZzfqSJRPRgzPJnDwwjCuBTbrV4XK
z/wfw9zFoNmwouu4z72Yg8JPO7DS0jmHR1z1CZwKdoq1BXyg9F3w+eRfaV9lQZ2e
SGbUGps3CYiHYrgqTwAfHEH1CK7ENGQW6Dd41k27N1EJyZKEN56c6G/+lHEGts20
FQIDAQAB
-----END PUBLIC KEY-----"""

# The landing page carries three shapes of the same link, all equivalent:
#   /dl/<id>/<key>        the current canonical form
#   /dl/<id>#<key>        older form -- the key was a fragment, so it never hit
#                         the server; the app read it from location.hash
#   /4.0/dl/<id>#<key>    a pinned-web-engine-version variant of the above
_LINK_RE = re.compile(
    r"^https?://(?P<host>[A-Za-z0-9.\-]+)(?:/\d+(?:\.\d+)*)?"
    r"/dl/(?P<link_id>[^/?#]+)[/#](?P<link_key>[^/?#]+)"
)

# sync.com error codes worth naming.
ERR_PASSWORD_REQUIRED = {8018, 8019}
ERR_SUSPENDED = {8025, 8051}


class SyncLinkError(RuntimeError):
    """An API-level failure from sync.com."""

    def __init__(self, message: str, code: int | None = None):
        super().__init__(message)
        self.code = code


def sha1_hex(text: str) -> str:
    """SJCL ``digest.hash`` equivalent -- SHA-1 hex over the UTF-8 bytes."""
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def _b64(data: bytes | str) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return base64.b64encode(data).decode("ascii")


def _aes_gcm_decrypt(key: bytes, blob: bytes) -> bytes:
    """Decrypt sync.com's ``iv || ciphertext || tag`` packing (96-bit tag)."""
    if len(blob) < 12 + 12:
        raise SyncLinkError("encrypted blob too short")
    iv, rest = blob[:12], blob[12:]
    ciphertext, tag = rest[:-12], rest[-12:]
    decryptor = Cipher(
        algorithms.AES(key), modes.GCM(iv, tag, min_tag_length=12)
    ).decryptor()
    return decryptor.update(ciphertext) + decryptor.finalize()


def _strip_prefix(value: str, expected: int) -> bytes:
    """Split ``"<prefix>:<base64>"`` and return the decoded payload."""
    prefix, _, payload = value.partition(":")
    if prefix != str(expected):
        raise SyncLinkError(f"expected enc prefix {expected}, got {prefix!r}")
    return base64.b64decode(payload)


@dataclass
class Item:
    """One entry in a shared folder."""

    sync_id: int
    name: str
    is_dir: bool
    size: int
    cachekey: str
    enc_data_key: str
    enc_share_name: str
    usertime: int = 0
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def mimetype(self) -> str:
        guessed, _ = mimetypes.guess_type(self.name)
        return guessed or "application/octet-stream"


class SyncLink:
    """A single password-protected sync.com download link."""

    def __init__(
        self,
        url: str,
        password: str,
        session: requests.Session | None = None,
        timeout: int = 60,
    ):
        match = _LINK_RE.match(url.strip())
        if not match:
            raise ValueError(f"not a sync.com /dl/ link: {url!r}")
        self.host = match.group("host")
        self.link_id = match.group("link_id")
        # sanitizeKey() in the web app: only [0-9a-zA-Z-] survive.
        self.link_key = re.sub(r"[^0-9a-zA-Z-]", "", match.group("link_key"))
        self.page_url = f"https://{self.host}/dl/{self.link_id}/{self.link_key}"

        self.passwordlock = sha1_hex(password) if password else None
        self.timeout = timeout

        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT, "Accept": "*/*"})

        self._pubkey = load_pem_public_key(COMPAT_PUBKEY_PEM.encode("ascii"))
        self._sharekey: bytes | None = None
        self._name_cache: dict[str, str] = {}
        self._encoding: str | None = None  # "json" or "form", learned on first call

        self.opened = False
        self.oid: int | None = None
        self.compat = False
        self.compat_hosts: list[str] = []
        self.web_hosts: list[str] = []
        # Returned alongside the data keys by pathdata; the web app forwards it
        # into the download item.
        self.previewtoken: str | None = None
        self.root_sync_id: int | None = None
        self.root_name: str | None = None

    # ------------------------------------------------------------------ API

    def _post(self, url: str, params: dict[str, Any], body: dict[str, Any]):
        """POST the body, negotiating JSON vs form encoding once per link.

        The Angular client sends JSON; older sync.com endpoints accept
        ``form-encoded`` with a JSON ``input_data`` field. We try JSON first and
        remember whichever the server actually likes.
        """
        attempts = ("json", "form") if self._encoding is None else (self._encoding,)
        last: Any = None
        for encoding in attempts:
            if encoding == "json":
                response = self.session.post(
                    url, params=params, json=body, timeout=self.timeout
                )
            else:
                response = self.session.post(
                    url,
                    params=params,
                    data={"input_data": __import__("json").dumps(body)},
                    timeout=self.timeout,
                )
            last = response
            try:
                data = response.json()
            except ValueError:
                continue
            # A structured reply means the server understood the encoding, even
            # if it is reporting an application-level error.
            if "success" in data or "error_code" in data or "errcode" in data:
                self._encoding = encoding
                return data
        raise SyncLinkError(
            f"no usable reply (HTTP {getattr(last, 'status_code', '?')}): "
            f"{getattr(last, 'text', '')[:200]!r}"
        )

    def _api(self, command: str, payload: dict[str, Any]) -> dict[str, Any]:
        url = f"https://{self.host}/api/v1/{command}"
        params = {
            "engine": ENGINE,
            "userid": 0,
            "deviceid": 0,
            "devicetypeid": 3,
        }
        body = {k: v for k, v in payload.items() if v is not None}
        data = self._post(url, params, body)

        if not data.get("success"):
            code = data.get("error_code") or data.get("errcode")
            hint = ""
            if code in ERR_PASSWORD_REQUIRED:
                hint = " -- wrong or missing link password"
            elif code in ERR_SUSPENDED:
                hint = " -- link is suspended"
            raise SyncLinkError(
                f"{command} failed (code {code}){hint}: {data.get('error_msg', '')}",
                code=code,
            )
        return data

    # ------------------------------------------------------------- crypto

    def _derive_sharekey(self, meta: dict[str, Any]) -> bytes:
        if meta.get("linkversion") == 2:
            salt = meta["salt"]
            salt_bytes = bytes.fromhex(salt) if isinstance(salt, str) else bytes(salt)
            iterations = int(meta.get("iterations") or 10000)
            return hashlib.pbkdf2_hmac(
                "sha256", self.link_key.encode("utf-8"), salt_bytes, iterations, 64
            )
        # linkversion 1: the URL key *is* the base64 share key.
        return base64.b64decode(self.link_key)

    def _decrypt_name(self, enc_share_name: str) -> str:
        cached = self._name_cache.get(enc_share_name)
        if cached is not None:
            return cached
        blob = _strip_prefix(enc_share_name, 1)
        plain = _aes_gcm_decrypt(self._sharekey[32:64], blob).decode("utf-8")
        self._name_cache[enc_share_name] = plain
        return plain

    def _decrypt_data_key(self, enc_data_key: str) -> str:
        """Return the plaintext data key, base64-encoded (as the app does)."""
        blob = _strip_prefix(enc_data_key, 2)
        return _b64(_aes_gcm_decrypt(self._sharekey[0:32], blob))

    def _compat_encrypt(self, text: str) -> str:
        """RSA-PKCS1v1.5 to sync.com's compat key, base64 (``compatDatakeyEncrypt``)."""
        return _b64(self._pubkey.encrypt(text.encode("utf-8"), asym_padding.PKCS1v15()))

    # -------------------------------------------------------------- public

    def open(self) -> "SyncLink":
        """Fetch link metadata, derive the share key. Call once before listing."""
        meta = self._api(
            "linkpathlist",
            {"publink_id": self.link_id, "passwordlock": self.passwordlock},
        )
        self._sharekey = self._derive_sharekey(meta)
        self.oid = meta.get("oid")
        self.compat = bool(meta.get("compat"))
        self.compat_hosts = list(meta.get("servers_compat") or [])
        self.web_hosts = list(meta.get("servers_web") or [])

        cwd = meta.get("cwd") or {}
        self.root_sync_id = cwd.get("sync_id")
        if cwd.get("enc_share_name"):
            # Also the first proof that the share key is right.
            self.root_name = self._decrypt_name(cwd["enc_share_name"])
        self.opened = True
        return self

    def listdir(self, sync_id: int | None = None) -> list[Item]:
        """List one folder. ``None`` lists the link root."""
        if not self.opened:
            self.open()
        meta = self._api(
            "linkpathlist",
            {
                "publink_id": self.link_id,
                "sync_id": sync_id,
                "passwordlock": self.passwordlock,
            },
        )
        items: list[Item] = []
        for entry in meta.get("pathitems") or []:
            enc_name = entry.get("enc_share_name") or ""
            # One entry with a missing or unreadable encrypted name must not cost
            # us the whole folder: site 095 has such an entry at its root and it
            # took the entire site's plan down with it. Keep the item with a
            # placeholder name so it stays visible in listings and notes.
            try:
                name = self._decrypt_name(enc_name)
            except (SyncLinkError, ValueError, UnicodeDecodeError) as exc:
                name = f"<undecryptable name: {exc}>"
            items.append(
                Item(
                    sync_id=entry["sync_id"],
                    name=name,
                    is_dir=entry.get("type") == "dir",
                    size=int(entry.get("size") or 0),
                    cachekey=entry.get("cachekey") or "",
                    enc_data_key=entry.get("enc_data_key") or "",
                    enc_share_name=enc_name,
                    usertime=int(entry.get("usertime") or 0),
                    raw=entry,
                )
            )
        return items

    def find(self, sync_id: int | None, name: str) -> Item | None:
        """Case-insensitive lookup of a single child by name."""
        target = name.strip().lower()
        for item in self.listdir(sync_id):
            if item.name.strip().lower() == target:
                return item
        return None

    def fetch_data_keys(self, items: Iterable[Item]) -> None:
        """Fill in ``enc_data_key`` for ``items`` via the ``pathdata`` call.

        ``linkpathlist`` returns ``enc_data_key`` empty for every file -- the web
        app fetches the keys separately in ``getFileKeys()`` immediately before
        building a download URL, and its response also carries the ``sharekeys``
        and ``previewtoken`` that ``mkDownloadItem()`` consumes. Batched, because
        the call takes a list.
        """
        pending = [i for i in items if not i.is_dir and not i.enc_data_key]
        if not pending:
            return

        pathitems = [
            {
                "share_id": item.raw.get("share_id"),
                "blob_id": item.raw.get("blob_id"),
                "sync_id": item.sync_id,
                # base64 of the lowercase extension, no leading dot.
                "ext": _b64(os.path.splitext(item.name)[1].lstrip(".").lower()),
                "link_cachekey": self.link_id,
                "size": item.size,
                "user_id": 0,
            }
            for item in pending
        ]
        result = self._api(
            "pathdata",
            {"pathitems": pathitems, "passwordlock": self.passwordlock},
        )
        datakeys = result.get("datakeys") or {}
        self.previewtoken = result.get("previewtoken") or self.previewtoken
        for item in pending:
            # JSON object keys arrive as strings; be tolerant of either.
            entry = datakeys.get(str(item.sync_id)) or datakeys.get(item.sync_id) or {}
            item.enc_data_key = entry.get("enc_data_key") or ""

    def download_url(self, item: Item) -> str:
        """Ask the server to sign a download request and build the compat URL."""
        if item.is_dir:
            raise ValueError(f"{item.name!r} is a directory")
        if not item.enc_data_key:
            self.fetch_data_keys([item])
        if not item.enc_data_key:
            raise SyncLinkError(
                f"{item.name!r} has no data key, and pathdata did not supply one"
            )

        data_key = self._decrypt_data_key(item.enc_data_key)
        quoted = urllib.parse.quote(item.name)
        disposition = (
            f'Content-Disposition: attachment; filename="{quoted}";'
            f"filename*=UTF-8''{quoted};"
        )
        req = {
            "sharelink_id": item.sync_id,
            "linkoid": self.oid,
            "linkcachekey": self.link_id,
            "mode": 101,
            "datakey": self._compat_encrypt(data_key).replace("=", ""),
            "header1": _b64("Content-Type: " + item.mimetype).replace("=", ""),
            "header2": _b64(disposition).replace("=", ""),
            "uagent": sha1_hex(USER_AGENT),
            "ipaddress": "s",
            "errurl": self._compat_encrypt(_b64(self.page_url)),
            "timestamp": int(time.time() * 1000),
            "engine": DOWNLOAD_ENGINE,
        }

        signed = self._api(
            "linksignrequest", {"req": req, "passwordlock": self.passwordlock}
        )
        params = signed.get("response") or {}
        pltoken = signed.get("pltoken")

        hosts = self.compat_hosts if (self.compat and self.compat_hosts) else self.web_hosts
        if not hosts:
            raise SyncLinkError("no download host advertised by the link")

        # Verbatim from mkDownloadPubLinkPath():
        #     for (const S in y) o.push(`${S}=${y[S]}`)
        #     o.push("cachekey=" + _.cachekey)
        #     v && o.push("pltoken=" + v)
        # Values are concatenated RAW -- no percent-encoding. The server signed
        # them as-is, so encoding them changes what it verifies. Only the
        # filename in the path is encoded.
        pairs = [f"{key}={value}" for key, value in params.items()]
        pairs.append(f"cachekey={item.cachekey}")
        if pltoken:
            pairs.append(f"pltoken={pltoken}")
        return f"https://{hosts[0]}/p/{quoted}?" + "&".join(pairs)

    def download(
        self,
        item: Item,
        dest_path: str,
        chunk_size: int = 1 << 20,
        progress: Any = None,
    ) -> int:
        """Stream ``item`` to ``dest_path``. Returns bytes written.

        Writes to ``<dest>.part`` and renames on success, so an interrupted run
        never leaves a truncated file that a later pass would treat as complete.
        """
        url = self.download_url(item)
        part = dest_path + ".part"
        os.makedirs(os.path.dirname(os.path.abspath(dest_path)), exist_ok=True)

        written = 0
        with self.session.get(
            url,
            stream=True,
            timeout=self.timeout,
            cookies={"passwordlock": urllib.parse.quote(self.passwordlock or "")},
        ) as response:
            if response.status_code != 200:
                raise SyncLinkError(
                    f"download of {item.name!r} failed: HTTP "
                    f"{response.status_code} {response.text[:200]!r}"
                )
            with open(part, "wb") as handle:
                for chunk in response.iter_content(chunk_size=chunk_size):
                    if not chunk:
                        continue
                    handle.write(chunk)
                    written += len(chunk)
                    if progress:
                        progress(written)

        if item.size and written != item.size:
            os.remove(part)
            raise SyncLinkError(
                f"{item.name!r}: expected {item.size} bytes, got {written}"
            )
        os.replace(part, dest_path)
        return written

    # ------------------------------------------------------------ helpers

    def walk(self, sync_id: int | None = None, prefix: str = "") -> Iterable[tuple[str, Item]]:
        """Depth-first walk yielding ``(path, item)``. Use sparingly -- one API
        call per directory."""
        for item in self.listdir(sync_id):
            path = f"{prefix}/{item.name}" if prefix else item.name
            yield path, item
            if item.is_dir:
                yield from self.walk(item.sync_id, path)
