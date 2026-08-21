"""local_llm.py - run an instruction over a text with a LOCAL model (Ollama).

Write an INSTRUCTION (summarize, rewrite, extract, answer a question...) and
point it at a text; it runs that on a local Ollama model and prints/saves the
result. Nothing leaves your machine, so you can do this on confidential material.
Free and offline: the LLM counterpart to audio_transcriber's local Whisper.

One ollama.chat() call. No agent, no cloud, no API key.

Setup:
    # install Ollama from https://ollama.com, then pull a model once:
    #   ollama pull llama3.2:1b
    pip install ollama
    python local_llm.py
"""

GUI = True  # show this script in the Automation GUI window

# ================= CONFIG - edit these, then run =================
INSTRUCTION = "Summarize this in 5 bullet points."  # what to do with the text
INPUT_FILE = r"C:\path\to\document.txt"  # the text to process
SOURCE_TEXT = ""  # ...or paste the text here if INPUT_FILE is blank/missing

MODEL = "llama3.2:1b"  # any model you have pulled in Ollama (e.g. llama3.1, qwen2.5, mistral)
TEXT_CHAR_LIMIT = 12000  # cap how much text is sent (fits the model's context)

SAVE_TO_FILE = False
OUTPUT_FILE = r"C:\path\to\output.txt"  # used only if SAVE_TO_FILE
# ================================================================

import sys
from pathlib import Path


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
    try:
        import ollama
    except ImportError:
        sys.exit("This needs the Ollama client: pip install ollama")

    text = load_text()
    prompt = f"{INSTRUCTION}\n\n---\n{text}"
    print(f"Running on local model '{MODEL}'...\n")
    try:
        resp = ollama.chat(model=MODEL, messages=[{"role": "user", "content": prompt}])
    except Exception as exc:
        sys.exit(
            f"Could not run the model: {exc}\n"
            f"Is Ollama running, and have you pulled the model?  ollama pull {MODEL}"
        )

    message = getattr(resp, "message", None) or resp["message"]
    content = (getattr(message, "content", None) or message["content"]).strip()
    print(content)

    if SAVE_TO_FILE:
        Path(OUTPUT_FILE).parent.mkdir(parents=True, exist_ok=True)
        Path(OUTPUT_FILE).write_text(content, encoding="utf-8")
        print(f"\nSaved to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
