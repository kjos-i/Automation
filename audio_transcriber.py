"""audio_transcriber.py - transcribe audio/video to text, locally.

Point it at an audio (or video) file, or a folder of them, and it writes a .txt
transcript for each. Runs Whisper LOCALLY via faster-whisper: free, and the audio
never leaves your machine. It downloads the model once (tiny ~75MB ... large ~3GB),
then reuses it.

Local by design: this is the one script here where nothing has to leave your
machine, which matters for confidential recordings.

Setup:
    pip install faster-whisper
    python audio_transcriber.py
"""

# ================= CONFIG - edit these, then run =================
AUDIO = r"C:\path\to\audio_or_folder"  # a single file, or a folder of recordings
RECURSIVE = False  # if AUDIO is a folder, also search subfolders?
FILE_TYPES = [".mp3", ".wav", ".m4a", ".mp4", ".ogg", ".flac", ".webm"]

MODEL = "base"  # faster-whisper size: tiny / base / small / medium / large
LANGUAGE = None  # None = auto-detect; or a code like "en", "no"

OUTPUT_DIR = ""  # where to write .txt transcripts; "" = next to each audio file
# ================================================================

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


def make_transcriber():
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        sys.exit("This needs faster-whisper: pip install faster-whisper")
    print(f"Loading faster-whisper '{MODEL}' (first run downloads the weights)...")
    model = WhisperModel(MODEL, device="auto", compute_type="default")

    def transcriber(path: Path) -> str:
        kwargs = {"language": LANGUAGE} if LANGUAGE else {}
        segments, _info = model.transcribe(str(path), **kwargs)
        return " ".join(seg.text.strip() for seg in segments).strip()

    return transcriber


def main() -> None:
    files = gather_audio()
    if not files:
        print("No matching audio files found.")
        return

    transcribe = make_transcriber()

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
