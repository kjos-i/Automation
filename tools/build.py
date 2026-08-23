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


def secret_values() -> dict[str, bytes]:
    """The real secrets from `.env`, to search the build for.

    Short values are skipped: a port number or a database name would match
    somewhere in 4,000 files and say nothing.
    """
    env = REPO / ".env"
    if not env.exists():
        return {}
    found: dict[str, bytes] = {}
    for line in env.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, _, value = line.partition("=")
        value = value.strip().strip("\"'")
        if len(value) >= 12:
            found[name.strip()] = value.encode()
    return found


def assert_no_secrets() -> None:
    """Refuse to ship a folder containing a real credential.

    `git ls-files` should already make this impossible, since a file that
    cannot be published cannot be packaged either. This checks the ARTEFACT
    rather than the rule, so the guarantee does not rest on `.gitignore`
    staying correct, and it fails the build loudly instead of shipping quietly.

    Nothing is printed but names and a verdict, so running the build never puts
    a secret on screen or in a log.
    """
    secrets = secret_values()
    if not secrets:
        print("  no .env to check against")
        return
    files = [p for p in OUT.rglob("*") if p.is_file()]
    leaked: list[str] = []
    for path in files:
        try:
            blob = path.read_bytes()
        except OSError:
            continue
        for name, value in secrets.items():
            if value in blob:
                leaked.append(f"{name} in {path.relative_to(OUT)}")
    if leaked:
        raise SystemExit("REFUSED, a secret is in the build:\n  " + "\n  ".join(leaked))
    print(f"  {len(files)} file(s) checked against {len(secrets)} secret(s): clean")


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

    print("secret scan")
    assert_no_secrets()

    scripts = [p for p in files if p.suffix == ".py" and p.parent == REPO]
    size = sum(f.stat().st_size for f in OUT.rglob("*") if f.is_file()) // 1048576
    print(f"\n{OUT}")
    print(f"  {len(scripts)} scripts, {len(files)} tracked files, {size} MB")
    print(f"  run it with: {interpreter} gui\\app.py")


if __name__ == "__main__":
    main()
