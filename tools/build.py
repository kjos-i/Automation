"""Assemble a self-contained Automation folder: the app plus its own Python.

    python tools/build.py

Produces `build/Automation/`, a folder that runs on a machine with no Python
installed and no internet connection. That folder is what the installer packs;
nothing here makes an installer.

Downloads are cached in `build/cache/`, so a rebuild is offline and quick. The
whole of `build/` is gitignored.

What goes in, and why each part:

  python/           A relocatable CPython from python-build-standalone. Not
                    python.org's embeddable zip, which ships without pip and
                    would break the window's Check installs / Install missing.
  python/.../app/   flet-windows.zip, the desktop client. flet_desktop looks
                    here BEFORE it downloads, so the first launch is offline.
  gui/, *.py, ...   Whatever `git ls-files` reports, minus this folder. Using
                    git rather than a hand-written list means the installer can
                    never quietly ship something the repo does not.

Versions are pinned rather than ranged: the folder should hold what was tested,
not whatever was newest on build day.
"""

from __future__ import annotations

import shutil
import subprocess
import tarfile
import urllib.request
from pathlib import Path

# ================= CONFIG - edit these, then run =================
PYTHON_VERSION = "3.13.15"  # Matches the 3.13 line this was developed against.
PYTHON_BUILD = "20260814"  # python-build-standalone release tag.
FLET_VERSION = "0.85.1"  # The version the GUI was verified on, not the newest.
PINNED = [  # Only what the WINDOW needs; each script's own packages are
    f"flet[desktop]=={FLET_VERSION}",  # fetched later by Install missing, which
    "keyring==25.7.0",  # is the whole point of those buttons.
    "python-dotenv==1.2.3",
]
# ================================================================

DEBUG_CMD = """@echo off
rem Same window, with a console attached so you can see what went wrong.
rem
rem The shortcut runs pythonw.exe, which shows no console, so a failure before
rem the window appears is silent: double-clicking looks like nothing happened.
rem Run this instead and the reason is printed here.
cd /d "%~dp0"
"%~dp0python\\python.exe" "%~dp0gui\\app.py"
echo.
echo Automation exited with code %errorlevel%.
pause
"""
"""Written into the built folder rather than kept in the repo: it runs the
bundled Python, which only exists in an installed copy."""

REPO = Path(__file__).resolve().parent.parent
BUILD = REPO / "build"
CACHE = BUILD / "cache"
OUT = BUILD / "Automation"

PYTHON_ASSET = f"cpython-{PYTHON_VERSION}+{PYTHON_BUILD}-x86_64-pc-windows-msvc-install_only.tar.gz"
PYTHON_URL = f"https://github.com/astral-sh/python-build-standalone/releases/download/{PYTHON_BUILD}/{PYTHON_ASSET}"
FLET_ASSET = "flet-windows.zip"
FLET_URL = f"https://github.com/flet-dev/flet/releases/download/v{FLET_VERSION}/{FLET_ASSET}"


def fetch(url: str, dest: Path) -> Path:
    """Download once. A cached file is trusted on name, which is safe here
    because every name carries its version."""
    if dest.exists():
        print(f"  cached  {dest.name} ({dest.stat().st_size // 1048576} MB)")
        return dest
    print(f"  fetching {dest.name}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    partial = dest.with_suffix(dest.suffix + ".part")
    with urllib.request.urlopen(url) as response, partial.open("wb") as out:
        shutil.copyfileobj(response, out)
    partial.replace(dest)
    print(f"  got     {dest.name} ({dest.stat().st_size // 1048576} MB)")
    return dest


def shipped_files() -> list[Path]:
    """Every tracked file, minus this tooling.

    `git ls-files` rather than a glob, so anything gitignored (the mail
    connectors, test_files, build/) is excluded by the same rule that keeps it
    out of the repo, and a new script needs no change here.
    """
    listed = subprocess.run(
        ["git", "ls-files"], cwd=REPO, capture_output=True, text=True, check=True
    ).stdout.split()
    skip = (".gitignore", "tools/", "images/gui.gif")
    return [REPO / f for f in listed if not f.startswith(skip)]


def main() -> None:
    if OUT.exists():
        print(f"clearing {OUT}")
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)

    print("downloads")
    python_archive = fetch(PYTHON_URL, CACHE / PYTHON_ASSET)
    flet_archive = fetch(FLET_URL, CACHE / FLET_ASSET)

    print("python")
    with tarfile.open(python_archive) as tar:
        tar.extractall(OUT, filter="data")  # unpacks as `python/`
    interpreter = OUT / "python" / "python.exe"
    if not interpreter.exists():
        raise SystemExit(f"no interpreter at {interpreter}")

    print("packages")
    subprocess.run(
        [
            str(interpreter),
            "-m",
            "pip",
            "install",
            "--quiet",
            "--disable-pip-version-check",
            "--no-warn-script-location",
            *PINNED,
        ],
        check=True,
    )

    print("flet client")
    app_dir = OUT / "python" / "Lib" / "site-packages" / "flet_desktop" / "app"
    app_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(flet_archive, app_dir / FLET_ASSET)
    # Ask flet_desktop itself rather than trusting the name above: it decides
    # the filename from the platform and the desktop flavour.
    wanted = subprocess.run(
        [str(interpreter), "-c", "import flet_desktop as f; print(f.get_artifact_filename())"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    if wanted != FLET_ASSET:
        raise SystemExit(f"flet_desktop wants {wanted}, we shipped {FLET_ASSET}")

    print("app")
    files = shipped_files()
    for path in files:
        target = OUT / path.relative_to(REPO)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)

    print("debug.cmd")
    (OUT / "debug.cmd").write_text(DEBUG_CMD, encoding="utf-8")

    scripts = [p for p in files if p.suffix == ".py" and p.parent == REPO]
    size = sum(f.stat().st_size for f in OUT.rglob("*") if f.is_file()) // 1048576
    print(f"\n{OUT}")
    print(f"  {len(scripts)} scripts, {len(files)} tracked files, {size} MB")
    print(f"  run it with: {interpreter} gui\\app.py")


if __name__ == "__main__":
    main()
