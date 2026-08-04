"""form_from_text.py - fill a form from a long text (one-shot extraction).

Define a form (FORM_FIELDS) at the top, point it at a text file (or paste text
inline), and it extracts those fields from the text in a single structured LLM
call and writes them out as JSON. It fills only what is actually in the text and
leaves anything it cannot find as null, so it never invents a value; it also
reports which required fields were missing.

Design: one LLM call with structured output. No agent, no chat. The data already
exists in the text, so a single extraction is the right tool.

Setup:
    pip install openai python-dotenv
    # put your key in a .env file next to this script:
    #   OPENAI_API_KEY=sk-...
    python form_from_text.py
"""

# ================= CONFIG - edit these, then run =================
# The form to fill. Each field has a name and a plain-language description the
# model uses to find it. Change these to whatever form you need.
FORM_NAME = "Contact intake"
FORM_FIELDS = [
    {"name": "full_name", "description": "the person's full name", "required": True},
    {"name": "email", "description": "a contact email address", "required": True},
    {"name": "reason", "description": "why they are getting in touch", "required": True},
    {"name": "phone", "description": "a phone number", "required": False},
]

INPUT_FILE = r"C:\path\to\long_text.txt"  # the text to extract from
SOURCE_TEXT = ""  # ...or paste the text here if INPUT_FILE is left blank/missing

MODEL = "gpt-4o-mini"
TEXT_CHAR_LIMIT = 12000  # cap how much text is sent, to bound cost

SAVE_TO_FILE = True
OUTPUT_FILE = r"C:\path\to\form_result.json"  # used only if SAVE_TO_FILE
# ================================================================

import json
import os
import sys
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from openai import OpenAI
from pydantic import Field, create_model

SYSTEM_PROMPT = (
    "You extract form fields from a text. Use ONLY information that is actually "
    "present in the text. If a field is not stated, leave it null. Never guess, "
    "infer beyond what is written, or invent a value."
)


def build_form_model():
    """Build a Pydantic model from FORM_FIELDS (every field optional so missing
    ones come back as null)."""
    definitions = {
        f["name"]: (Optional[str], Field(default=None, description=f["description"]))
        for f in FORM_FIELDS
    }
    return create_model("FormData", **definitions)


def load_text() -> str:
    path = Path(INPUT_FILE)
    if INPUT_FILE and path.is_file():
        text = path.read_text(encoding="utf-8", errors="replace")
    elif SOURCE_TEXT.strip():
        text = SOURCE_TEXT
    else:
        sys.exit("No input text. Set INPUT_FILE to a readable file, or paste into SOURCE_TEXT.")
    return text[:TEXT_CHAR_LIMIT]


def main() -> None:
    load_dotenv()
    if not os.getenv("OPENAI_API_KEY"):
        sys.exit(
            "No OPENAI_API_KEY found. Put it in a .env file next to this script:\n"
            "  OPENAI_API_KEY=sk-..."
        )
    client = OpenAI()
    form_model = build_form_model()
    text = load_text()

    print(f"Extracting '{FORM_NAME}' from {len(text)} characters of text...\n")
    completion = client.beta.chat.completions.parse(
        model=MODEL,
        temperature=0,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"FORM: {FORM_NAME}\n\nTEXT:\n{text}"},
        ],
        response_format=form_model,
    )
    values = completion.choices[0].message.parsed.model_dump()

    for f in FORM_FIELDS:
        val = values.get(f["name"])
        tag = "" if f["required"] else " (optional)"
        print(f"  {f['name']}{tag}: {val if val is not None else '(not found)'}")

    missing = [f["name"] for f in FORM_FIELDS if f["required"] and not values.get(f["name"])]
    if missing:
        print(f"\nMissing required field(s) not found in the text: {', '.join(missing)}")

    if SAVE_TO_FILE:
        Path(OUTPUT_FILE).parent.mkdir(parents=True, exist_ok=True)
        Path(OUTPUT_FILE).write_text(
            json.dumps(values, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        print(f"\nSaved to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
