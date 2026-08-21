"""random_picker.py - pick random items from a folder, a list file, or a list.

Give it a source and how many to pick; it picks that many at random and prints
them. For a folder it can also copy the picked files aside or save the list. Set
SEED to a number to make the pick reproducible (same seed gives the same result),
which is handy for drawing a fair, repeatable sample of files or records to review.

No AI, no network: sometimes the right tool is ten lines of the standard library.

Setup:
    # nothing to install (standard library only)
    python random_picker.py
"""

GUI = True  # show this script in the Automation GUI window

# ================= CONFIG - edit these, then run =================
SOURCE = r"C:\path\to\folder"  # a folder, OR a .txt file (one item per line), OR "" to use ITEMS
ITEMS = []  # inline list, used only if SOURCE is blank
FILE_TYPES = []  # folder source: limit types, e.g. [".pdf"]; empty = all files
RECURSIVE = False  # folder source: include subfolders?

COUNT = 1  # how many to pick
SEED = None  # set an int for a reproducible pick; None = truly random

COPY_TO = r""  # folder source: copy the picked files here (blank = don't)
SAVE_LIST_TO = r""  # write the picked list to this file (blank = don't)
# ================================================================

import random
import shutil
import sys
from pathlib import Path


def gather():
    """Return (items, kind) where kind is 'folder' | 'lines' | 'list'."""
    if not SOURCE:
        if not ITEMS:
            sys.exit("No source. Set SOURCE to a folder or .txt file, or fill ITEMS.")
        return list(ITEMS), "list"
    p = Path(SOURCE)
    if p.is_dir():
        wanted = {t.lower() for t in FILE_TYPES}
        globber = p.rglob("*") if RECURSIVE else p.glob("*")
        files = [
            f for f in sorted(globber) if f.is_file() and (not wanted or f.suffix.lower() in wanted)
        ]
        return files, "folder"
    if p.is_file():
        lines = [ln.strip() for ln in p.read_text(encoding="utf-8", errors="replace").splitlines()]
        return [ln for ln in lines if ln], "lines"
    sys.exit(f"SOURCE not found: {SOURCE}")


def main() -> None:
    items, kind = gather()
    if not items:
        print("Nothing to pick from.")
        return

    if SEED is not None:
        random.seed(SEED)
    n = min(COUNT, len(items))
    if n < COUNT:
        print(f"(only {len(items)} item(s) available; picking {n})")
    picks = random.sample(items, n)

    print(f"Picked {n} of {len(items)}:")
    for item in picks:
        print(f"  {item.name if kind == 'folder' else item}")

    if kind == "folder" and COPY_TO:
        dest = Path(COPY_TO)
        dest.mkdir(parents=True, exist_ok=True)
        for f in picks:
            shutil.copy2(f, dest / f.name)
        print(f"\nCopied {n} file(s) to {COPY_TO}")

    if SAVE_LIST_TO:
        lines = [str(x) if kind == "folder" else x for x in picks]
        Path(SAVE_LIST_TO).parent.mkdir(parents=True, exist_ok=True)
        Path(SAVE_LIST_TO).write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"Saved list to {SAVE_LIST_TO}")


if __name__ == "__main__":
    main()
