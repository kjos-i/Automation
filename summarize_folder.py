"""summarize_folder.py - summarize every document in a folder into one index.

Point it at a folder; it summarizes each document in a few sentences, then writes
a single markdown index: an overview of the whole collection followed by a
per-file summary. Reads .txt/.md out of the box; .pdf/.docx via optional
pypdf/python-docx.

Design: a map-reduce - summarize each file (map), then summarize the summaries
(reduce). No agent; the steps are fixed.

Setup:
    pip install google-genai python-dotenv
    # optional, for those formats:  pip install pypdf python-docx
    # put your key in a .env file next to this script:
    #   GOOGLE_API_KEY=...
    python summarize_folder.py
"""

GUI = True  # show this script in the Automation GUI window

# ================= CONFIG - edit these, then run =================
FOLDER =  r"C:\path\to\documents"
RECURSIVE = False
FILE_TYPES = [".txt", ".md"]  # add ".pdf" / ".docx" (needs pypdf / python-docx)

SUMMARY_SENTENCES = 3  # rough length of each per-document summary
OVERALL_SUMMARY = True  # also write an overview of the whole collection

MODEL = "gemini-3.5-flash-lite"  # a free-tier model; for higher quality use a bigger/Pro model (paid)
CHAR_LIMIT = 20000  # how much of each document to send (Gemini handles a lot); None = no cap (whole document)

OUTPUT_FILE = r"C:\path\to\SUMMARY.md"
# ================================================================

import os
import sys
from collections.abc import Iterator
from pathlib import Path

from dotenv import load_dotenv
from google import genai


# --- Finding and reading documents ---
def iter_documents() -> Iterator[Path]:
    base = Path(FOLDER)
    if not base.is_dir():
        sys.exit(f"FOLDER not found or not a folder: {FOLDER}")
    wanted = {t.lower() for t in FILE_TYPES}
    globber = base.rglob("*") if RECURSIVE else base.glob("*")
    for p in sorted(globber):
        if p.is_file() and p.suffix.lower() in wanted:
            yield p


def read_document(path: Path) -> str | None:
    """Return the document's text, or None if it cannot be read."""
    suffix = path.suffix.lower()
    if suffix in (".txt", ".md"):
        return path.read_text(encoding="utf-8", errors="replace")[:CHAR_LIMIT]
    if suffix == ".pdf":
        try:
            from pypdf import PdfReader
        except ImportError:
            print(f"  ! skipping {path.name}: run 'pip install pypdf' to read PDFs")
            return None
        try:
            reader = PdfReader(str(path))
            return "\n".join((page.extract_text() or "") for page in reader.pages)[:CHAR_LIMIT]
        except Exception as exc:
            print(f"  ! could not read {path.name}: {exc}")
            return None
    if suffix == ".docx":
        try:
            import docx
        except ImportError:
            print(f"  ! skipping {path.name}: run 'pip install python-docx' to read .docx")
            return None
        try:
            document = docx.Document(str(path))
            return "\n".join(p.text for p in document.paragraphs)[:CHAR_LIMIT]
        except Exception as exc:
            print(f"  ! could not read {path.name}: {exc}")
            return None
    return None


# --- Gemini calls ---
def summarize_one(client, name: str, text: str) -> str:
    prompt = (
        f"Summarize the following document in about {SUMMARY_SENTENCES} sentences, "
        f"plainly and factually.\n\nDocument: {name}\n\n{text}"
    )
    resp = client.models.generate_content(model=MODEL, contents=prompt)
    return (resp.text or "").strip()


def summarize_overall(client, summaries: list) -> str:
    joined = "\n".join(f"- {name}: {summary}" for name, summary in summaries)
    prompt = (
        "Here are short summaries of documents in one folder. Write a brief overview "
        "(a few sentences) of what the collection covers as a whole.\n\n" + joined
    )
    resp = client.models.generate_content(model=MODEL, contents=prompt)
    return (resp.text or "").strip()


def build_report(summaries: list, overall: str) -> str:
    lines = [f"# Folder summary: {FOLDER}", "", f"{len(summaries)} document(s) summarized.", ""]
    if overall:
        lines += ["## Overview", "", overall, ""]
    lines += ["## Documents", ""]
    for name, summary in summaries:
        lines += [f"### {name}", "", summary, ""]
    return "\n".join(lines)


def main() -> None:
    load_dotenv()
    if not os.getenv("GOOGLE_API_KEY"):
        sys.exit(
            "No GOOGLE_API_KEY found. Put it in a .env file next to this script:\n"
            "  GOOGLE_API_KEY=..."
        )
    client = genai.Client(api_key=os.getenv("GOOGLE_API_KEY"))

    print(f"Summarizing documents in: {FOLDER}\n")
    summaries = []
    for path in iter_documents():
        text = read_document(path)
        if not text:
            continue
        try:
            summary = summarize_one(client, path.name, text)
        except Exception as exc:
            print(f"  ! skipped {path.name} ({exc})")
            continue
        summaries.append((path.name, summary))
        print(f"  summarized {path.name}")

    if not summaries:
        print("Nothing summarized.")
        return

    overall = ""
    if OVERALL_SUMMARY and len(summaries) > 1:
        try:
            overall = summarize_overall(client, summaries)
        except Exception as exc:
            print(f"  ! overall summary failed ({exc})")

    report = build_report(summaries, overall)
    Path(OUTPUT_FILE).parent.mkdir(parents=True, exist_ok=True)
    Path(OUTPUT_FILE).write_text(report, encoding="utf-8")
    print(f"\nSaved index to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
