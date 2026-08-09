"""form_from_interview.py - fill a form by chatting, saved as JSON.

The conversational companion to form_from_text.py, using the same FORM_FIELDS.
It chats with you one question at a time, filling fields as you answer, and
stops once every required field is present, then saves the result as JSON. It
records only what you actually say and never invents a value.

This is the one script here that is genuinely a chat loop: you cannot fill a form
up front if the person has not given the answers yet, so a back-and-forth is the
right tool. (Most scripts in this repo are one-shot; this one is not.)

Setup:
    pip install openai python-dotenv
    # put your key in a .env file next to this script:
    #   OPENAI_API_KEY=sk-...
    python form_from_interview.py
"""

# ================= CONFIG - edit these, then run =================
FORM_NAME = "Contact intake"
FORM_FIELDS = [
    {"name": "full_name", "description": "the person's full name", "required": True},
    {"name": "email", "description": "a contact email address", "required": True},
    {"name": "reason", "description": "why they are getting in touch", "required": True},
    {"name": "phone", "description": "a phone number", "required": False},
]

MODEL = "gpt-4o-mini"
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


def _fields_brief() -> str:
    lines = []
    for f in FORM_FIELDS:
        req = "required" if f["required"] else "optional"
        lines.append(f"- {f['name']} ({req}): {f['description']}")
    return "\n".join(lines)


SYSTEM_PROMPT = (
    f"You collect a form called '{FORM_NAME}' by chatting with the user, one "
    "question at a time. The fields are:\n"
    f"{_fields_brief()}\n\n"
    "From the conversation so far, fill `fields` with everything the user has "
    "given (leave anything not yet provided null; never invent). If any REQUIRED "
    "field is still missing, set complete=false and put a short, friendly question "
    "for the next missing field in `reply`. When every required field is present, "
    "set complete=true and put a brief confirmation of what you collected in `reply`."
)


def build_turn_model():
    """A per-turn response: the fields so far, the next thing to say, and whether
    the form is done. FormData is built from FORM_FIELDS (all optional)."""
    field_defs = {
        f["name"]: (Optional[str], Field(default=None, description=f["description"]))
        for f in FORM_FIELDS
    }
    form_data = create_model("FormData", **field_defs)
    return create_model(
        "Turn",
        fields=(form_data, ...),
        reply=(str, ...),
        complete=(bool, ...),
    )


def save(values: dict) -> None:
    Path(OUTPUT_FILE).parent.mkdir(parents=True, exist_ok=True)
    Path(OUTPUT_FILE).write_text(
        json.dumps(values, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"\nSaved to {OUTPUT_FILE}")


def main() -> None:
    load_dotenv()
    if not os.getenv("OPENAI_API_KEY"):
        sys.exit(
            "No OPENAI_API_KEY found. Put it in a .env file next to this script:\n"
            "  OPENAI_API_KEY=sk-..."
        )
    client = OpenAI()
    turn_model = build_turn_model()

    print(f"Filling '{FORM_NAME}'. Type 'exit' or 'quit' to stop.\n")
    conversation: list = []  # list of (role, content)

    while True:
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        if conversation:
            messages += [{"role": r, "content": c} for r, c in conversation]
        else:
            messages.append({"role": "user", "content": "Please begin."})

        turn = (
            client.beta.chat.completions.parse(
                model=MODEL, temperature=0, messages=messages, response_format=turn_model
            )
            .choices[0]
            .message.parsed
        )

        print(f"Assistant: {turn.reply}\n")
        conversation.append(("assistant", turn.reply))

        if turn.complete:
            values = turn.fields.model_dump()
            print("Collected:")
            for f in FORM_FIELDS:
                print(f"  {f['name']}: {values.get(f['name'])}")
            if SAVE_TO_FILE:
                save(values)
            break

        try:
            user = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nStopped.")
            break
        if user.lower() in ("exit", "quit"):
            print("Stopped before the form was complete.")
            break
        conversation.append(("user", user))
        print()


if __name__ == "__main__":
    main()
