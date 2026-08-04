"""rename_files.py - bulk-rename files in a folder, safely.

Rename every file in a folder by simple rules (lowercase, replace spaces, add a
date prefix, number them, strip junk) with no LLM and no dependencies. Or flip
USE_LLM on to let a model propose clean names from the filename (and, optionally,
the text of .txt/.md files).

Safe by design: it prints a dry-run table (old -> new) and only renames when you
set APPLY = True. It never overwrites (colliding names get a _1, _2 suffix) and
it renames in two phases, so files can even swap names cleanly.

The default rules mode is the point: plenty of everyday automation needs no AI at
all. Reach for the model only when the filenames are genuinely uninformative.

Setup:
    # rules mode: nothing to install (standard library only)
    # LLM mode (USE_LLM=True): pip install openai python-dotenv, and a .env with
    #   OPENAI_API_KEY=sk-...
    python rename_files.py
"""

# ================= CONFIG - edit these, then run =================
FOLDER = r"C:\path\to\folder"
RECURSIVE = False
FILE_TYPES = []  # empty = all files; or [".pdf", ".jpg"] to limit

# --- Rule-based (no LLM, no dependencies) ---
LOWERCASE = True
SPACES_TO = "_"  # replace spaces with this; "" removes them; None leaves them
DATE_PREFIX = False  # prefix with the file's modified date: 2026-08-04_
SEQUENTIAL = False  # add a running number: 001_, 002_, ...
STRIP_REGEX = ""  # delete text matching this regex, e.g. r"copy|final|\(1\)"

# --- Optional LLM assist ---
USE_LLM = False
INSTRUCTION = "Make a short, clear, lowercase-hyphenated name."
READ_CONTENT = False  # let the model read text-file content (.txt/.md only; costs tokens)
MODEL = "gpt-4o-mini"

# --- Safety ---
APPLY = False  # False = dry-run preview only; True = actually rename
# ================================================================

import os
import re
import sys
from datetime import datetime
from pathlib import Path


def sanitize(name: str) -> str:
    """Drop characters that are illegal in filenames."""
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", name).strip() or "unnamed"


def rule_name(path: Path, index: int) -> str:
    stem = path.stem
    if STRIP_REGEX:
        stem = re.sub(STRIP_REGEX, "", stem)
    if LOWERCASE:
        stem = stem.lower()
    if SPACES_TO is not None:
        stem = stem.replace(" ", SPACES_TO)
    stem = stem.strip(" _-")
    prefixes = []
    if DATE_PREFIX:
        prefixes.append(datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d"))
    if SEQUENTIAL:
        prefixes.append(f"{index:03d}")
    stem = "_".join([*prefixes, stem]).strip("_") or "unnamed"
    return sanitize(stem) + path.suffix.lower()


def llm_name(client, path: Path) -> str:
    content = ""
    if READ_CONTENT and path.suffix.lower() in (".txt", ".md"):
        try:
            content = path.read_text(encoding="utf-8", errors="replace")[:1500]
        except OSError:
            content = ""
    prompt = f"{INSTRUCTION}\n\nCurrent filename: {path.name}"
    if content:
        prompt += f"\n\nFile content (excerpt):\n{content}"
    prompt += "\n\nReturn ONLY the new base name, without the extension, path, or quotes."
    resp = client.chat.completions.create(
        model=MODEL, temperature=0, messages=[{"role": "user", "content": prompt}]
    )
    base = resp.choices[0].message.content.strip().strip('"').strip()
    return sanitize(base) + path.suffix.lower()


def dedupe(name: str, used: set) -> str:
    """Ensure the new name is unique within its folder; append _1, _2 if needed."""
    if name.lower() not in used:
        used.add(name.lower())
        return name
    stem, suffix = os.path.splitext(name)
    i = 1
    while f"{stem}_{i}{suffix}".lower() in used:
        i += 1
    result = f"{stem}_{i}{suffix}"
    used.add(result.lower())
    return result


def gather_files() -> list:
    base = Path(FOLDER)
    if not base.is_dir():
        sys.exit(f"FOLDER not found or not a folder: {FOLDER}")
    wanted = {t.lower() for t in FILE_TYPES}
    globber = base.rglob("*") if RECURSIVE else base.glob("*")
    return [
        p for p in sorted(globber) if p.is_file() and (not wanted or p.suffix.lower() in wanted)
    ]


def main() -> None:
    files = gather_files()
    if not files:
        print("No matching files found.")
        return

    client = None
    if USE_LLM:
        try:
            from dotenv import load_dotenv
            from openai import OpenAI
        except ImportError:
            sys.exit("USE_LLM needs: pip install openai python-dotenv")
        load_dotenv()
        if not os.getenv("OPENAI_API_KEY"):
            sys.exit("USE_LLM needs OPENAI_API_KEY in a .env file next to this script.")
        client = OpenAI()

    used_by_dir: dict = {}
    plan = []  # (old_path, new_name)
    for i, path in enumerate(files, 1):
        new = llm_name(client, path) if USE_LLM else rule_name(path, i)
        new = dedupe(new, used_by_dir.setdefault(path.parent, set()))
        plan.append((path, new))

    changed = [(p, n) for p, n in plan if p.name != n]
    print(f"{len(files)} file(s) scanned, {len(changed)} would change:\n")
    for p, n in plan:
        print(f"  = {p.name}" if p.name == n else f"  {p.name}  ->  {n}")

    if not APPLY:
        print("\nDRY RUN - set APPLY = True to actually rename.")
        return
    if not changed:
        print("\nNothing to rename.")
        return

    # Two-phase rename so files can swap names without clobbering each other.
    staged = []
    for i, (path, new) in enumerate(changed):
        tmp = path.with_name(f".rn_tmp_{i}_{path.name}")
        path.rename(tmp)
        staged.append((tmp, new))
    for tmp, new in staged:
        tmp.rename(tmp.with_name(new))
    print(f"\nRenamed {len(staged)} file(s).")


if __name__ == "__main__":
    main()
