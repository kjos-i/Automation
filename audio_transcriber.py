"""audio_transcriber.py - transcribe audio/video to text.

Point it at an audio (or video) file, or a folder of them, and it writes a .txt
transcript for each. Two engines, one flag:

  ENGINE = "faster-whisper"  -> runs Whisper LOCALLY. Free, and the audio never
                               leaves your machine. Downloads the model once
                               (tiny ~75MB ... large ~3GB), then reuses it.
  ENGINE = "openai"          -> uses the cloud Whisper API. No setup, but pay per
                               minute and the audio is uploaded (25MB per file).

Local-first on purpose: this is the one script here where nothing has to leave
your machine, which matters for confidential recordings.

Setup:
    # local (default):
    pip install faster-whisper
    # cloud:
    pip install openai python-dotenv        # and a .env with OPENAI_API_KEY=sk-...
    python audio_transcriber.py
"""

# ================= CONFIG - edit these, then run =================
AUDIO = r"C:\path\to\audio_or_folder"  # a single file, or a folder of recordings
RECURSIVE = False  # if AUDIO is a folder, also search subfolders?
FILE_TYPES = [".mp3", ".wav", ".m4a", ".mp4", ".ogg", ".flac", ".webm"]

ENGINE = "faster-whisper"  # "faster-whisper" (local, free, private) | "openai" (cloud)
MODEL = "base"  # faster-whisper size: tiny/base/small/medium/large (ignored for openai)
LANGUAGE = None  # None = auto-detect; or a code like "en", "no"

OUTPUT_DIR = ""  # where to write .txt transcripts; "" = next to each audio file
# ================================================================

import os
import sys
from pathlib import Path


def gather_audio() -> list:
    p = Path(AUDIO)
    if p.is_file():
        return [p]
    if p.is_dir():
        wanted = {t.lower() for t in FILE_TYPES}
        globber = p.rglob("*") if RECURSIVE else p.glob("*")
        return [f for f in sorted(globber) if f.is_file() and f.suffix.lower() in wanted]
    sys.exit(f"AUDIO not found: {AUDIO}")


def make_local_transcriber():
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        sys.exit("faster-whisper engine needs: pip install faster-whisper")
    print(f"Loading faster-whisper '{MODEL}' (first run downloads it)...")
    model = WhisperModel(MODEL, device="auto", compute_type="default")

    def transcribe(path: Path) -> str:
        kwargs = {"language": LANGUAGE} if LANGUAGE else {}
        segments, _info = model.transcribe(str(path), **kwargs)
        return " ".join(seg.text.strip() for seg in segments).strip()

    return transcribe


def make_openai_transcriber():
    try:
        from dotenv import load_dotenv
        from openai import OpenAI
    except ImportError:
        sys.exit("openai engine needs: pip install openai python-dotenv")
    load_dotenv()
    if not os.getenv("OPENAI_API_KEY"):
        sys.exit("openai engine needs OPENAI_API_KEY in a .env file next to this script.")
    client = OpenAI()

    def transcribe(path: Path) -> str:
        kwargs = {"language": LANGUAGE} if LANGUAGE else {}
        with open(path, "rb") as fh:
            resp = client.audio.transcriptions.create(model="whisper-1", file=fh, **kwargs)
        return resp.text.strip()

    return transcribe


def main() -> None:
    files = gather_audio()
    if not files:
        print("No matching audio files found.")
        return

    if ENGINE == "faster-whisper":
        transcribe = make_local_transcriber()
    elif ENGINE == "openai":
        transcribe = make_openai_transcriber()
    else:
        sys.exit(f"Unknown ENGINE: {ENGINE!r} (use 'faster-whisper' or 'openai')")

    out_dir = Path(OUTPUT_DIR) if OUTPUT_DIR else None
    for path in files:
        print(f"Transcribing {path.name} ...")
        try:
            text = transcribe(path)
        except Exception as exc:
            print(f"  ! failed: {exc}")
            continue
        target_dir = out_dir if out_dir else path.parent
        target_dir.mkdir(parents=True, exist_ok=True)
        dest = target_dir / (path.stem + ".txt")
        dest.write_text(text, encoding="utf-8")
        preview = text[:120].replace("\n", " ")
        print(f"  -> {dest}  ({len(text)} chars)\n     {preview}...")


if __name__ == "__main__":
    main()
