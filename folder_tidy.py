"""folder_tidy.py - sort a folder into category subfolders, safely.

List the CATEGORIES you want; it reads each file (its name, or .txt/.md content
if READ_CONTENT is on), picks the best-fit category, and files it into a
subfolder of that name. Safe by design: it prints a dry-run table (file ->
category) and only moves anything when APPLY = True. It never overwrites
(colliding names get a _1 suffix) and skips files that are already sorted.

Design: one classification call per file. No agent. Unlike rename_files (rules,
no AI), sorting by *meaning* into your own categories is a judgement a rules
engine cannot make, so here an LLM earns its place.

Setup:
    pip install openai python-dotenv
    # put your key in a .env file next to this script:
    #   OPENAI_API_KEY=sk-...
    python folder_tidy.py
"""

# ================= CONFIG - edit these, then run =================
FOLDER = r"C:\path\to\folder"
RECURSIVE = False
FILE_TYPES = []  # [] = all files; or list any extensions to limit, e.g. [".pdf", ".jpg"]

CATEGORIES = ["Invoices", "Contracts", "Reports", "Personal", "Other"]  # subfolders to sort into
READ_CONTENT = False  # read .txt/.md content to classify (else filename only)
MODEL = "gpt-4o-mini"

APPLY = False  # False = dry-run preview only; True = actually move the files
# ================================================================

import os
import shutil
import sys
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI


def gather_files() -> list:
    base = Path(FOLDER)
    if not base.is_dir():
        sys.exit(f"FOLDER not found or not a folder: {FOLDER}")
    category_dirs = {c.lower() for c in CATEGORIES}
    wanted = {t.lower() for t in FILE_TYPES}
    globber = base.rglob("*") if RECURSIVE else base.glob("*")
    files = []
    for p in sorted(globber):
        if not p.is_file():
            continue
        if wanted and p.suffix.lower() not in wanted:
            continue
        if p.parent.name.lower() in category_dirs:  # already sorted
            continue
        files.append(p)
    return files


def classify(client: OpenAI, path: Path) -> str:
    content = ""
    if READ_CONTENT and path.suffix.lower() in (".txt", ".md"):
        try:
            content = path.read_text(encoding="utf-8", errors="replace")[:1500]
        except OSError:
            content = ""
    prompt = (
        f"Sort this file into exactly one of these categories: {', '.join(CATEGORIES)}.\n"
        f"Filename: {path.name}"
    )
    if content:
        prompt += f"\n\nContent excerpt:\n{content}"
    prompt += "\n\nReply with ONLY the category name, exactly as written above."
    resp = client.chat.completions.create(
        model=MODEL, temperature=0, messages=[{"role": "user", "content": prompt}]
    )
    answer = resp.choices[0].message.content.strip()
    for cat in CATEGORIES:
        if answer.lower() == cat.lower():
            return cat
    return CATEGORIES[-1]  # fall back to the last category if the reply is off-list


def move_into(path: Path, category: str) -> None:
    dest_dir = Path(FOLDER) / category
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / path.name
    if dest.exists():
        i = 1
        while (dest_dir / f"{dest.stem}_{i}{dest.suffix}").exists():
            i += 1
        dest = dest_dir / f"{dest.stem}_{i}{dest.suffix}"
    shutil.move(str(path), str(dest))


def main() -> None:
    load_dotenv()
    if not os.getenv("OPENAI_API_KEY"):
        sys.exit(
            "No OPENAI_API_KEY found. Put it in a .env file next to this script:\n"
            "  OPENAI_API_KEY=sk-..."
        )
    client = OpenAI()

    files = gather_files()
    if not files:
        print("No matching files to sort.")
        return

    plan = []
    for path in files:
        try:
            category = classify(client, path)
        except Exception as exc:
            print(f"  ! skipped {path.name} ({exc})")
            continue
        plan.append((path, category))

    print(f"{len(plan)} file(s):\n")
    for path, category in plan:
        print(f"  {path.name}  ->  {category}/")

    if not APPLY:
        print("\nDRY RUN - set APPLY = True to move the files.")
        return

    moved = 0
    for path, category in plan:
        try:
            move_into(path, category)
            moved += 1
        except OSError as exc:
            print(f"  ! could not move {path.name}: {exc}")
    print(f"\nMoved {moved} file(s).")


if __name__ == "__main__":
    main()
