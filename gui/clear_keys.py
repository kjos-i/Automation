"""Remove every credential this app stores. Run by the uninstaller.

    python gui/clear_keys.py

Prints how many were removed. Exits non-zero only if the credential store could
not be reached, so the uninstaller can tell "there were none" from "it failed".

A separate entry point rather than something in the window, because it runs
while the app is being deleted, with no window and nobody to click anything.
Which names exist is not listed here either: `catalog` reads each script's own
`os.getenv(...)` calls, so this removes exactly what the Keys dialog could set.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import catalog  # noqa: E402
import keys  # noqa: E402


def main() -> None:
    names = sorted(
        {name for script in catalog.discover(only_shown=False) for name in script.env_vars}
    )
    try:
        removed = keys.clear_many(names)
    except Exception as exc:  # the store itself is unreachable
        print(f"could not reach the credential store: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    print(f"removed {removed} of {len(names)} known credential name(s)")


if __name__ == "__main__":
    main()
