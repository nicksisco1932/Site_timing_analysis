"""Protocol primitives and link parsing. No network."""

from __future__ import annotations

import pytest
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from sync_tdc_logs.synclink import SyncLink, _aes_gcm_decrypt, _b64, sha1_hex

DUMMY = "not-a-real-password"


def test_signed_params_are_not_percent_encoded() -> None:
    """The server signs the param values verbatim, so encoding them breaks auth.

    Percent-encoding them returned sync.com's "Password Protected" HTML page --
    HTTP 200, 2,707 bytes -- instead of the file, for every download. The bundle's
    mkDownloadPubLinkPath() concatenates raw:

        for (const S in y) o.push(`${S}=${y[S]}`)
        o.push("cachekey=" + _.cachekey)
        v && o.push("pltoken=" + v)
    """
    from sync_tdc_logs.synclink import Item

    link = SyncLink("https://ln5.sync.com/dl/abc123/aaaa-bbbb-cccc-dddd", DUMMY)
    link.opened = True
    link.compat = True
    link.compat_hosts = ["m201.syncusercontent1.com"]
    link.oid = 1

    # Values full of characters urllib would escape: + / = :
    signed = {"datakey": "r8Hk+B12/zXS=", "signature": "abc123", "ipaddress": "3484"}
    link._api = lambda command, payload: {  # type: ignore[method-assign]
        "response": signed,
        "pltoken": "eyJwbCI6+x/y=",
    }
    link._decrypt_data_key = lambda enc: "plain-key"  # type: ignore[method-assign]
    link._compat_encrypt = lambda value: "ENC+/="  # type: ignore[method-assign]

    item = Item(
        sync_id=1,
        name="007_01-001 Tdc.zip",
        is_dir=False,
        size=10,
        cachekey="60:c3daa==",
        enc_data_key="2:something",
        enc_share_name="1:something",
    )
    url = link.download_url(item)

    for raw in ("datakey=r8Hk+B12/zXS=", "cachekey=60:c3daa==", "pltoken=eyJwbCI6+x/y="):
        assert raw in url, f"value was altered; expected {raw!r} in {url!r}"
    # Only the filename in the path is encoded.
    assert "/p/007_01-001%20Tdc.zip?" in url


def test_sha1_hex_known_answer() -> None:
    """passwordlock is SJCL's digest.hash: SHA-1 hex over the UTF-8 bytes."""
    assert sha1_hex("abc") == "a9993e364706816aba3e25717850c26c9cd0d89d"


def test_b64() -> None:
    assert _b64("hi") == "aGk="


def test_aes_gcm_96_bit_tag_round_trip() -> None:
    """sync.com packs iv || ciphertext || tag with a 96-bit (12-byte) tag."""
    key = bytes(range(32))
    iv = bytes(range(12))
    encryptor = Cipher(algorithms.AES(key), modes.GCM(iv, min_tag_length=12)).encryptor()
    name = b"007_01-001 Tdc.zip"
    ciphertext = encryptor.update(name) + encryptor.finalize()
    packed = iv + ciphertext + encryptor.tag[:12]
    assert _aes_gcm_decrypt(key, packed) == name


def test_aes_gcm_rejects_short_blob() -> None:
    with pytest.raises(Exception):
        _aes_gcm_decrypt(bytes(range(32)), b"too short")


CANONICAL = "https://ln5.sync.com/dl/1cc0491a0/bu6bds5k-n6kkcvtx-6xsyyfks-3a3227re"


@pytest.mark.parametrize(
    "url",
    [
        CANONICAL,
        # Older form: the key was a URL fragment, read from location.hash.
        "https://ln5.sync.com/dl/1cc0491a0#bu6bds5k-n6kkcvtx-6xsyyfks-3a3227re",
        # Version-pinned variant of the above.
        "https://ln5.sync.com/4.0/dl/1cc0491a0#bu6bds5k-n6kkcvtx-6xsyyfks-3a3227re",
    ],
)
def test_all_three_link_shapes_parse_identically(url: str) -> None:
    """The landing page publishes all three; 18 of 65 sites use the # forms."""
    link = SyncLink(url, DUMMY)
    assert link.host == "ln5.sync.com"
    assert link.link_id == "1cc0491a0"
    assert link.link_key == "bu6bds5k-n6kkcvtx-6xsyyfks-3a3227re"
    # page_url is normalised to the canonical slash form; it is echoed back to
    # the server as errurl, so it must not carry a fragment.
    assert link.page_url == CANONICAL


def test_passwordlock_is_a_sha1_hex_digest() -> None:
    link = SyncLink(CANONICAL, DUMMY)
    assert link.passwordlock == sha1_hex(DUMMY)
    assert len(link.passwordlock) == 40


def test_no_password_means_no_passwordlock() -> None:
    assert SyncLink(CANONICAL, "").passwordlock is None


def test_key_is_sanitised_like_the_web_app() -> None:
    """sanitizeKey() keeps only [0-9a-zA-Z-]."""
    link = SyncLink(f"{CANONICAL}?utm=x", DUMMY)
    assert link.link_key == "bu6bds5k-n6kkcvtx-6xsyyfks-3a3227re"


def test_rejects_non_dl_url() -> None:
    with pytest.raises(ValueError):
        SyncLink("https://profoundmedical.sharepoint.com/sites/com04", DUMMY)


def test_compat_rsa_output_length() -> None:
    """RSA-2048 PKCS1v15 -> 256 bytes -> 344 base64 chars.

    The web app loops until it sees exactly this length, so a mismatch means the
    hardcoded compat public key is wrong.
    """
    link = SyncLink(CANONICAL, DUMMY)
    assert len(link._compat_encrypt("test")) == 344
