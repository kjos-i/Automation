"""Run a script with the GUI's CONFIG values, without modifying the script.

How a run works:

1. The form's field texts are checked with `ast.literal_eval`. A bad value is
   reported against its own field and nothing is launched.
2. `build_source` returns the script's source with ONLY the CONFIG values
   swapped. Names, comments, imports and code are untouched, byte for byte.
3. That source is written to a twin, `_gui_run_<name>.py`, beside the original,
   and the twin is what runs. The original is never written to.
4. The twin is launched as a subprocess and its output is streamed line by line.
   It is deleted when the process ends, whether it finished or was stopped.

**Why a twin instead of importing the module and setting its globals**, which
would need no file at all: three scripts consume their config while the module
is still importing, before anything could be set - `web_search_agent.py` builds
its model and bakes MAX_SEARCHES into a prompt at import, `supervisor_agent.py`
builds its router, `form_from_interview.py` bakes FORM_NAME into a prompt.
Those three would silently run with the file's defaults while the GUI showed
the user's values. A twin cannot get that wrong for any script.

**Why the twin lives in `Automation/` and not a temp folder**: `scheduler.py`
resolves its target with `Path(__file__).with_name(...)`, and `load_dotenv()`
searches upward from the running file's directory to find `.env`. Move the
twin out of the folder and both break.
"""

from __future__ import annotations

import ast
import asyncio
import contextlib
import os
import runpy
import sys
from collections.abc import Callable
from pathlib import Path

from catalog import AUTOMATION_DIR, Script

TWIN_PREFIX = "_gui_run_"
"""Twins are named `_gui_run_<script>.py`. The leading underscore is what keeps
`catalog.discover` from listing a running twin as a script of its own."""

_CHILD_FLAG = "--gui-run-script"
"""Argument that turns this app into a plain script runner instead of a GUI.

Only used inside a packaged bundle, where there is no `python.exe` to call
because the bundle IS the interpreter. Costs nothing today and means
`flet pack` stays an afternoon rather than a redesign.
"""


def maybe_run_child() -> None:
    """If launched as `<app> --gui-run-script <path>`, run that script and exit.

    Called first thing in `main()`, before any GUI work. Outside a bundle this
    never fires, since the runner calls `python -u <twin>` directly.
    """
    if len(sys.argv) >= 3 and sys.argv[1] == _CHILD_FLAG:
        runpy.run_path(sys.argv[2], run_name="__main__")
        raise SystemExit(0)


def validate(script: Script, values: dict[str, str]) -> dict[str, str]:
    """Field name -> error message, empty when every value is valid Python.

    `ast.literal_eval` accepts exactly what a CONFIG block is allowed to hold:
    strings (raw ones included), numbers, booleans, None, lists, tuples, dicts.
    It refuses names, calls and f-strings, so a typo becomes a message on the
    offending row instead of a traceback three seconds into the run.
    """
    errors: dict[str, str] = {}
    for field in script.fields:
        text = values.get(field.name, field.literal).strip()
        if not text:
            errors[field.name] = 'empty - a value is required (use "" for an empty string)'
            continue
        try:
            ast.literal_eval(text)
        except (ValueError, SyntaxError, MemoryError, RecursionError) as exc:
            errors[field.name] = f"not a valid Python value: {exc}"
    return errors


def build_source(script: Script, values: dict[str, str]) -> str:
    """The script's source with the CONFIG values replaced.

    Each field carries the span of its VALUE only, so the constant name, the
    `=` and the trailing comment survive untouched. Spans are applied last
    first, so replacing one does not shift the ones above it.

    `ast` reports column offsets as UTF-8 byte offsets, so the slicing is done
    on encoded bytes. On an all-ASCII line that is the same thing; on a line
    holding an accented character it is the difference between a clean edit and
    a corrupted one.
    """
    lines = script.source.splitlines(keepends=True)
    for field in sorted(script.fields, key=lambda f: f.lineno, reverse=True):
        new = values.get(field.name, field.literal).strip()
        if new == field.literal:
            continue
        if field.lineno == field.end_lineno:
            raw = lines[field.lineno - 1].encode("utf-8")
            patched = raw[: field.col_offset] + new.encode("utf-8") + raw[field.end_col_offset :]
            lines[field.lineno - 1] = patched.decode("utf-8")
        else:
            head = lines[field.lineno - 1].encode("utf-8")[: field.col_offset].decode("utf-8")
            tail = (
                lines[field.end_lineno - 1].encode("utf-8")[field.end_col_offset :].decode("utf-8")
            )
            lines[field.lineno - 1 : field.end_lineno] = [head + new + tail]
    return "".join(lines)


def cleanup_twins(folder: Path | None = None) -> int:
    """Delete any `_gui_run_*.py` left behind, and return how many.

    Runs at startup. A twin is normally removed when its process ends, but a
    hard kill of the GUI itself (or a crash) can strand one, and a stray copy
    of a script in the folder is confusing to find later.
    """
    base = folder or AUTOMATION_DIR
    removed = 0
    for path in base.glob(f"{TWIN_PREFIX}*.py"):
        with contextlib.suppress(OSError):
            path.unlink()
            removed += 1
    return removed


def _command(twin: Path) -> list[str]:
    """The command line that runs `twin`.

    `-u` is not optional. Python block-buffers stdout when it is a pipe rather
    than a console, so without it a script's `print()` output would sit in an
    8 KB buffer and arrive in one lump at the end, when the same script in a
    terminal prints as it goes.
    """
    if getattr(sys, "frozen", False):
        return [sys.executable, _CHILD_FLAG, str(twin)]
    return [sys.executable, "-u", str(twin)]


def _child_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    """The environment for a run.

    `PYTHONUNBUFFERED` belts-and-braces the `-u` above, and also covers
    anything the script itself spawns. `PYTHONIOENCODING` matters more than it
    looks: writing to a pipe on Windows, Python encodes stdout with the system
    code page, so a single accented filename or arrow in a `print()` raises
    UnicodeEncodeError and kills the run. UTF-8 both ends removes that whole
    class of failure.

    `extra` carries the credentials from the Keys dialog, which is the GUI's
    only source for them. They go in the environment, never into the script's
    source, so a key can never end up written to a twin on disk. A script's own
    `load_dotenv()` defaults to `override=False`, so what is set here is what
    the script sees.
    """
    return {
        **os.environ,
        **(extra or {}),
        "PYTHONUNBUFFERED": "1",
        "PYTHONIOENCODING": "utf-8",
    }


class ScriptRun:
    """One in-flight run: writes the twin, streams the output, cleans up.

    `on_line` is called for each line of the script's stdout and stderr, merged
    so a traceback appears in the output in the order it happened. `on_done` is
    called once with the exit code, or None if the run was stopped.
    """

    def __init__(
        self,
        script: Script,
        source: str,
        on_line: Callable[[str], None],
        on_done: Callable[[int | None], None],
        env: dict[str, str] | None = None,
    ) -> None:
        self.script = script
        self.source = source
        self.on_line = on_line
        self.on_done = on_done
        self.env = env
        self.twin = script.path.with_name(f"{TWIN_PREFIX}{script.path.stem}.py")
        self._proc: asyncio.subprocess.Process | None = None
        self._stopped = False

    async def start(self) -> None:
        """Run to completion. Await this from `page.run_task`."""
        code: int | None = None
        try:
            self.twin.write_text(self.source, encoding="utf-8")
            self._proc = await asyncio.create_subprocess_exec(
                *_command(self.twin),
                cwd=str(self.script.path.parent),
                env=_child_env(self.env),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                # A generous line limit: the default 64 KB raises on any script
                # that prints a very long single line (a whole JSON payload,
                # say), which would end the run for a cosmetic reason.
                limit=1024 * 1024,
            )
            await self._pump()
            code = await self._proc.wait()
        except OSError as exc:
            self.on_line(f"[gui] could not start the script: {exc}")
        finally:
            with contextlib.suppress(OSError):
                self.twin.unlink()
            self.on_done(None if self._stopped else code)

    async def _pump(self) -> None:
        """Forward the child's output a line at a time until it closes."""
        stream = self._proc.stdout if self._proc else None
        if stream is None:
            return
        while True:
            try:
                raw = await stream.readline()
            except (ValueError, asyncio.LimitOverrunError):
                # A line longer than the limit above. Take what is buffered
                # rather than ending the run.
                raw = await stream.read(65536)
            if not raw:
                return
            self.on_line(raw.decode("utf-8", errors="replace").rstrip("\r\n"))

    def stop(self) -> None:
        """Ask the script to stop, then insist.

        `terminate()` on Windows is a TerminateProcess, so the script gets no
        chance to clean up - acceptable here, since the scripts that need
        stopping are the ones looping on a timer (`web_search` REPEAT,
        `scheduler`) and they hold nothing that a stop would corrupt.

        Known limit: this kills the script, not any process the script itself
        spawned. `scheduler.py` launches other scripts, so a stop while it has
        a child running leaves that child to finish.
        """
        self._stopped = True
        proc = self._proc
        if proc is None or proc.returncode is not None:
            return
        with contextlib.suppress(ProcessLookupError, OSError):
            proc.terminate()
