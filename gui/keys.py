"""API keys and mailbox credentials, held in the OS credential store.

Where they live: Windows Credential Manager, via `keyring`, under the service
name `automation`. Not a JSON file, nothing in plain text on disk.

This is the GUI's ONLY source of credentials. Someone using the window has no
terminal and no `.env`, so the dialog has to be the whole story: what is in a
field is what the scripts get. The values are passed into each run as
environment variables, never written into the script source, so nothing secret
ever reaches a file on disk.

Which names exist is not a list kept here: `catalog` reads each script's own
`os.getenv(...)` calls, so the dialog shows exactly the credentials the scripts
ask for and stays right by itself.
"""

from __future__ import annotations

import logging

import keyring
import keyring.errors

logger = logging.getLogger(__name__)

KEYRING_SERVICE = "automation"
"""Service name the credentials are filed under in Windows Credential Manager.
Distinct from the sibling apps' own services, so nothing collides."""

_SECRET_SUFFIXES = ("_KEY", "_TOKEN", "_PASSWORD", "_SECRET")
"""What makes a value secret, and so masked in the dialog behind a reveal
button. Everything else (`GMAIL_ADDRESS`, `OUTLOOK_ADDRESS`) is an ordinary
setting that happens to sit beside the secrets: it is your own email address,
so masking it helps nobody."""


def is_secret(name: str) -> bool:
    """Whether `name` holds a secret, and so is masked in the dialog."""
    return name.endswith(_SECRET_SUFFIXES)


def get(name: str) -> str:
    """The stored value for `name`, or "" if there is none."""
    try:
        return keyring.get_password(KEYRING_SERVICE, name) or ""
    except keyring.errors.KeyringError:
        logger.warning("could not read %s from the credential store", name)
        return ""


def is_set(name: str) -> bool:
    """Whether a value is stored, without revealing it."""
    return bool(get(name))


def save(name: str, value: str) -> None:
    """Store `name`. An empty value removes it instead, so clearing a field in
    the dialog and saving is how a credential is deleted."""
    try:
        if value:
            keyring.set_password(KEYRING_SERVICE, name, value)
        else:
            clear(name)
    except keyring.errors.KeyringError:
        logger.warning("could not save %s to the credential store", name)
        raise


def clear(name: str) -> None:
    """Remove `name` from the store. Silent if it was not there."""
    try:
        keyring.delete_password(KEYRING_SERVICE, name)
    except keyring.errors.PasswordDeleteError:
        pass
    except keyring.errors.KeyringError:
        logger.warning("could not clear %s from the credential store", name)
        raise


def as_env(names: tuple[str, ...] | list[str]) -> dict[str, str]:
    """The stored values among `names`, ready to merge into a run's environment.

    Only names that actually hold a value are returned. An unset credential is
    left out rather than handed an empty string, which `os.getenv` would treat
    as present and which would defeat each script's own "no key found" message.
    """
    found = {}
    for name in names:
        value = get(name)
        if value:
            found[name] = value
    return found
