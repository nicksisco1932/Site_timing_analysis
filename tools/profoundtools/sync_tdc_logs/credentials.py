"""Resolve the sync.com link password from the OS keyring, with env-var fallback.

Every site link on the landing page shares one password, so there is exactly one
secret to manage.

Local use: store it once via ``sync-tdc-logs setup``.
CI / automation: set ``SYNC_LINK_PASSWORD``; it takes precedence over the keyring.

The password is never written to ``sites.json`` or to a saved plan.
"""

from __future__ import annotations

import getpass
import os

import keyring

# Stored under the user's OS credential store; visible in Windows Credential
# Manager -> Generic Credentials.
SERVICE = "sync-tdc-logs:link"
USERNAME = "password"
ENV_VAR = "SYNC_LINK_PASSWORD"


def load(allow_prompt: bool = True) -> str:
    """Return the link password, or raise RuntimeError explaining how to set it."""
    password = os.environ.get(ENV_VAR) or keyring.get_password(SERVICE, USERNAME)
    if not password and allow_prompt:
        password = getpass.getpass("sync.com link password: ")
    if not password:
        raise RuntimeError(
            "No sync.com link password available.\n"
            f"Run `sync-tdc-logs setup` to store it in the OS keyring, "
            f"or set the {ENV_VAR} environment variable."
        )
    return password


def store(password: str) -> None:
    """Persist the link password to the OS keyring."""
    keyring.set_password(SERVICE, USERNAME, password)


def forget() -> bool:
    """Remove the stored password. Returns False if there was none."""
    try:
        keyring.delete_password(SERVICE, USERNAME)
        return True
    except keyring.errors.PasswordDeleteError:
        return False
