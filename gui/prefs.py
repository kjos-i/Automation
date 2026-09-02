"""Which tiles this user has hidden, remembered between runs.

The ONE piece of state the app keeps outside the scripts, and it is here for a
reason worth stating. Everything the window shows is read from the script files
themselves, and the README promises the app "reads the scripts; it never
rewrites them". Hiding a tile used to break that promise: it wrote `GUI = False`
into the file, which edited a distributed, version-controlled script to record a
personal preference. In a git checkout that turned unticking a few tiles into a
pile of modified files waiting to be committed by accident.

So the two ideas are now separate:

  - `GUI = False` IN THE SCRIPT is the author saying this one is not ready, or is
    meant for a terminal. The window ignores it completely - not on the rail, not
    in the Scripts dialog. It is an editor's switch, and every shipped script
    arrives `True`, so someone who only uses the window never meets it.
  - HIDDEN HERE is the user saying "not on my rail". Reversible from the dialog,
    because the script is still listed there with its box unticked.

Stored in the user's own data folder rather than beside the app, so that
upgrading or reinstalling does not discard it, and so nothing has to be
writable in the install folder.

A missing, unreadable or corrupt file means "nothing hidden". That is the right
failure: a preference that cannot be read must never stop the window listing the
scripts, and showing a tile too many is a smaller error than hiding one the user
wanted.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

APP_DIR_NAME = "Automation"
FILE_NAME = "prefs.json"
_HIDDEN_KEY = "hidden"


def prefs_path() -> Path:
    """Where the preferences file lives, per platform.

    `%APPDATA%` on Windows, `~/.config` elsewhere (honouring `XDG_CONFIG_HOME`),
    which is where a small per-user settings file belongs on each.
    """
    base = os.environ.get("APPDATA") or os.environ.get("XDG_CONFIG_HOME")
    root = Path(base) if base else Path.home() / ".config"
    return root / APP_DIR_NAME / FILE_NAME


def _read() -> dict:
    try:
        with prefs_path().open(encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def hidden() -> set[str]:
    """File names the user has taken off the rail, e.g. {"web_search.py"}.

    Stored by NAME rather than by full path: the same folder is the whole world
    here, and a path would break the moment the app moved or was reinstalled
    somewhere else, silently un-hiding everything.
    """
    value = _read().get(_HIDDEN_KEY)
    return {str(name) for name in value} if isinstance(value, list) else set()


def set_hidden(names: set[str]) -> None:
    """Replace the hidden set. Raises OSError if it cannot be written.

    The caller reports that, rather than this swallowing it: a preference that
    silently fails to save is worse than one that says so, because the user finds
    out by watching their choice undo itself on the next launch.
    """
    path = prefs_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    data = _read()
    data[_HIDDEN_KEY] = sorted(names)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2)
