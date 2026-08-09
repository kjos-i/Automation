"""meeting_notes.py - turn a transcript into structured minutes.

Feed it a transcript (a text file, or pasted inline) and it extracts meeting
minutes in one structured LLM call: a short summary, the decisions made, action
items with owners, and open questions. It writes clean markdown (and the raw
JSON is easy to add if you want it).

Pairs with audio_transcriber.py (point INPUT_FILE at its .txt output), but works
on any transcript: a Teams/Zoom export, or something you typed.

Design: one structured-output call. It uses only what the transcript says and
never invents decisions or owners.

Setup:
    pip install openai python-dotenv
    # put your key in a .env file next to this script:
    #   OPENAI_API_KEY=sk-...
    python meeting_notes.py
"""

# ================= CONFIG - edit these, then run =================
INPUT_FILE = r"C:\path\to\transcript.txt"  # any text file (.txt/.md/.vtt/.srt...), not PDF/Word
SOURCE_TEXT = ""  # ...or paste the transcript here if INPUT_FILE is blank/missing

MODEL = "gpt-4o-mini"
TEXT_CHAR_LIMIT = 40000  # cap chars sent (bounds cost); None = no cap (send whole transcript)

SAVE_TO_FILE = True
OUTPUT_FILE = r"C:\path\to\minutes.md"  # used only if SAVE_TO_FILE
# ================================================================

import os
import sys
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from openai import OpenAI
from pydantic import BaseModel

SYSTEM_PROMPT = (
    "You write meeting minutes from a transcript. Use ONLY what is actually said. "
    "Do not invent decisions, tasks, or owners. If an action item has no clear "
    "owner, leave the owner null. Keep the summary short and factual."
)


class ActionItem(BaseModel):
    task: str
    owner: Optional[str]  # who is responsible, or null if not stated


class Minutes(BaseModel):
    summary: str
    decisions: list[str]
    action_items: list[ActionItem]
    open_questions: list[str]


def load_text() -> str:
    path = Path(INPUT_FILE)
    if INPUT_FILE and path.is_file():
        text = path.read_text(encoding="utf-8", errors="replace")
    elif SOURCE_TEXT.strip():
        text = SOURCE_TEXT
    else:
        sys.exit("No transcript. Set INPUT_FILE to a readable file, or paste into SOURCE_TEXT.")
    return text[:TEXT_CHAR_LIMIT]


def render_markdown(m: Minutes) -> str:
    lines = ["# Meeting minutes", "", "## Summary", "", m.summary, ""]
    lines += ["## Decisions", ""]
    lines += [f"- {d}" for d in m.decisions] or ["- (none)"]
    lines += ["", "## Action items", ""]
    if m.action_items:
        for item in m.action_items:
            who = item.owner if item.owner else "unassigned"
            lines.append(f"- {item.task}  ({who})")
    else:
        lines.append("- (none)")
    lines += ["", "## Open questions", ""]
    lines += [f"- {q}" for q in m.open_questions] or ["- (none)"]
    return "\n".join(lines)


def main() -> None:
    load_dotenv()
    if not os.getenv("OPENAI_API_KEY"):
        sys.exit(
            "No OPENAI_API_KEY found. Put it in a .env file next to this script:\n"
            "  OPENAI_API_KEY=sk-..."
        )
    client = OpenAI()
    text = load_text()

    print(f"Reading {len(text)} characters of transcript...\n")
    completion = client.beta.chat.completions.parse(
        model=MODEL,
        temperature=0,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"TRANSCRIPT:\n{text}"},
        ],
        response_format=Minutes,
    )
    minutes = completion.choices[0].message.parsed
    report = render_markdown(minutes)
    print(report)

    if SAVE_TO_FILE:
        Path(OUTPUT_FILE).parent.mkdir(parents=True, exist_ok=True)
        Path(OUTPUT_FILE).write_text(report, encoding="utf-8")
        print(f"\nSaved to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
