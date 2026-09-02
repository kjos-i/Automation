"""Desktop GUI for the Automation scripts (Flet).

    python gui/app.py

One window, two columns:

    [ script rail | the selected script's CONFIG, Run, and its output ]

The right-hand page is the script's own CONFIG block, rendered line by line:
the constant name, an editable field holding the value's Python literal exactly
as it appears in the file, and the script's own trailing comment as the help
text. Nothing on that page was written by hand for the GUI, which is why a
script can be added to the folder and appear here with no code change.

Run writes a twin of the script with those values substituted and launches it;
the pane below streams its output. See `runner.py` for why a twin, and
`catalog.py` for how the fields are found. Neither ever writes to a script.

A script appears here when it says `GUI = True` above its CONFIG block, and the
user has not taken its tile off the rail in the Scripts dialog. No list of
scripts lives in this file.

Those two are deliberately separate. `GUI` is the AUTHOR's switch, meaning this
one is unfinished or belongs in a terminal, and the app never shows such a script
anywhere. The rail choice is the USER's, kept in `prefs.py` so that hiding a tile
does not edit a distributed file, and so it can be undone from the same dialog.
"""

from __future__ import annotations

import ast
import contextlib
import os
import sys
import threading
import time
from pathlib import Path

import flet as ft

# `python gui/app.py` already puts this folder on the path, so the sibling
# imports below resolve. The insert is for the other launch styles (`python -m
# gui.app`, or a packaged bundle) where the working directory is the parent.
sys.path.insert(0, str(Path(__file__).resolve().parent))

import catalog
import installs
import keys
import prefs
import runner
from _styles import (
    ACTIVE_BG,
    CODE_COMMENT_COLOR,
    CODE_NAME_COLOR,
    ERROR_COLOR,
    ERROR_SIZE,
    INPUT_TEXT_TOP,
    OUTPUT_SIZE,
    PAGE_BG,
    PANEL_TITLE_SIZE,
    RAIL_BG,
    RAIL_BUTTON_BG,
    SECTION_GAP,
    STATUS_TEXT_SIZE,
    SUBTITLE_SIZE,
    TILE_SUBTITLE_SIZE,
    TILE_TITLE_SIZE,
    apply_input_box,
    apply_status_style,
    code_text,
    panel_title,
    section_heading,
    spaced_row,
    spaced_rule,
    status_line,
    thin_rule,
)

WINDOW_WIDTH = 1180
WINDOW_HEIGHT = 820
WINDOW_MIN_WIDTH = 900
WINDOW_MIN_HEIGHT = 600

REPO_URL = "https://github.com/kjos-i/Automation"
"""Where the scripts come from, linked at the foot of the Add-scripts dialog.

That dialog lists every script on this machine, so it is where someone looking
for one that is not there ends up; the link is the whole update mechanism. An
installed copy is a snapshot of the scripts at build time, and the folder is the
user's own, so getting a newer script means either downloading the file into the
folder or re-running a newer installer. Both start here."""

ICON_PATH = catalog.AUTOMATION_DIR / "images" / "automation.ico"
"""The window's icon, and the one the installer puts on the shortcut. Found
relative to the scripts folder rather than to this file, so it resolves the
same way in the repo and in an installed copy."""

RAIL_WIDTH = 250
"""Fixed width for the script rail. Fixed rather than flexed so the code on the
right keeps a stable line width as the window resizes."""

RIGHT_PANE_PADDING = 24
"""Breathing room around the script's page. Wider than the rail's 10, because
this side holds dense monospace that would otherwise start hard against the
divider and run to the window edge."""

NAME_COLUMN_WIDTH = 180
"""Width of the constant-name column. Pinned so every `=` in the form lines up
down one edge, the way it does in the file. The longest name in the three
slice-1 scripts is TIMESTAMP_FILENAME."""

OUTPUT_MAX_LINES = 2000
"""How much of a run's output is kept. A bounded buffer, so a script that
prints per-file over a large folder cannot grow the window's memory without
limit. The full output is in the script's own files, not here."""

OUTPUT_REFRESH_SECONDS = 0.04
"""Minimum gap between repaints while output streams in. Without a throttle a
fast-printing script triggers a full page update per line, which is slower than
the script itself. Each repaint is also what moves the scroll, so this doubles
as how smoothly the pane follows: 0.08 made the movement visibly steppy."""


class AutomationGui:
    """The window: the rail, the form for the selected script, and one run."""

    def __init__(self, page: ft.Page) -> None:
        self.page = page
        self.scripts: list[catalog.Script] = []
        self.selected: catalog.Script | None = None
        self.file_picker = ft.FilePicker()

        # Controls rebuilt whenever a script is selected.
        self._inputs: dict[str, ft.Control] = {}
        self._errors: dict[str, ft.Text] = {}

        # The current run, and its output buffer.
        self._run: runner.ScriptRun | None = None
        self._lines: list[str] = []
        # Text the script has printed with no newline yet, held apart from
        # `_lines` because the next chunk either completes it or, if it is a
        # prompt, the answer is appended to it.
        self._pending = ""
        self._last_paint = 0.0

        # Long-lived controls.
        self._rail_list = ft.Column(spacing=6, scroll=ft.ScrollMode.AUTO, expand=True)
        self._header = ft.Column(spacing=2)
        self._needs = ft.Column(spacing=2)
        self._requirements = ft.Column(spacing=2)
        self._check_button = ft.Button(
            content=ft.Text("Check installs"), on_click=self._on_check, disabled=True
        )
        self._install_button = ft.Button(
            content=ft.Text("Install missing"), on_click=self._on_install, disabled=True
        )
        self._uninstall_button = ft.Button(
            content=ft.Text("Uninstall"), on_click=self._on_uninstall, disabled=True
        )
        # Filled by Check, cleared whenever a different script is selected, so a
        # stale answer from another script can never enable Install.
        self._missing: tuple[installs.Requirement, ...] = ()
        self._form = ft.Column(spacing=2, scroll=ft.ScrollMode.AUTO, expand=True)
        # One control per line, not one Text holding every line. `auto_scroll`
        # follows the end only when the list of CHILDREN changes, so a single
        # Text whose value grew never moved the view, and `scroll_to` on the
        # Column did not either. Appending a child is what Flet reacts to.
        self._output_list = ft.ListView(expand=True, auto_scroll=True, spacing=0)
        # Complete lines already turned into controls, so a repaint appends the
        # new ones instead of rebuilding two thousand.
        self._rendered = 0
        self._pending_control: ft.Text | None = None
        # Every run gets a stdin pipe, so this box answers any script that asks
        # a question. `form_from_interview` is the one that does today; nothing
        # here knows that, and a script that never reads stdin just ignores it.
        self._input = apply_input_box(
            ft.TextField(
                hint_text="Type an answer here and press Enter",
                dense=True,
                disabled=True,
                on_submit=self._on_send,
            )
        )
        self._status = status_line(idle=True)
        self._run_button = ft.Button(content=ft.Text("Run"), on_click=self._on_run, disabled=True)
        self._stop_button = ft.Button(
            content=ft.Text("Stop"), on_click=self._on_stop, disabled=True
        )

    # ----- construction -----------------------------------------------------

    def build(self) -> None:
        self.page.title = "Automation"
        self.page.theme_mode = ft.ThemeMode.DARK
        self.page.bgcolor = PAGE_BG
        self.page.padding = 0
        self.page.window.width = WINDOW_WIDTH
        self.page.window.height = WINDOW_HEIGHT
        self.page.window.min_width = WINDOW_MIN_WIDTH
        self.page.window.min_height = WINDOW_MIN_HEIGHT
        # The same .ico the installer gives the shortcut, so the title bar and
        # the taskbar show this app rather than Flet's own bird. Windows only,
        # and skipped if the file is absent, since a missing picture must never
        # stop the window opening.
        if ICON_PATH.exists():
            self.page.window.icon = str(ICON_PATH)

        stranded = runner.cleanup_twins()

        # Fill the rail BEFORE the tree is added to the page. Flet 0.85 does not
        # reliably push a list that is replaced after mounting, which is why the
        # first build of this window came up with an empty rail.
        self._load_scripts()

        rail = ft.Container(
            width=RAIL_WIDTH,
            bgcolor=RAIL_BG,
            padding=10,
            content=ft.Column(
                expand=True,
                spacing=8,
                horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
                controls=[
                    # The two app-wide buttons, full width of the rail (the
                    # Column is STRETCH) on a background darker than the rail.
                    # Padded as a group so they sit apart from the window edge
                    # above and the Scripts heading below.
                    ft.Container(
                        padding=ft.Padding.symmetric(vertical=SECTION_GAP),
                        content=ft.Column(
                            spacing=SECTION_GAP,
                            horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
                            controls=[
                                ft.Button(
                                    content=ft.Text("Keys"),
                                    icon=ft.Icons.KEY,
                                    tooltip="API keys and mailbox credentials",
                                    style=ft.ButtonStyle(bgcolor=RAIL_BUTTON_BG),
                                    on_click=self._on_keys,
                                ),
                                ft.Button(
                                    content=ft.Text("Add scripts"),
                                    icon=ft.Icons.PLAYLIST_ADD,
                                    tooltip="Choose which scripts appear in the list below",
                                    style=ft.ButtonStyle(bgcolor=RAIL_BUTTON_BG),
                                    on_click=self._on_add_scripts,
                                ),
                            ],
                        ),
                    ),
                    ft.Row(
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        controls=[
                            ft.Container(content=panel_title("Scripts"), expand=True),
                            ft.IconButton(
                                icon=ft.Icons.REFRESH,
                                tooltip="Rescan the folder",
                                on_click=self._on_refresh,
                            ),
                        ],
                    ),
                    thin_rule(),
                    self._rail_list,
                    # Below the list, where a quiet link belongs. The other
                    # GitHub link is at the foot of Add scripts, which nobody
                    # opens when they are stuck; this one is where help is
                    # looked for. A link rather than a button, so the rail
                    # keeps its two clean choices.
                    # Closed off by the same rule that sits under the Scripts
                    # heading, so the link reads as its own footer rather than
                    # as one more entry in the list.
                    thin_rule(),
                    ft.Container(
                        padding=ft.Padding.only(bottom=SECTION_GAP),
                        content=ft.Text(
                            size=TILE_SUBTITLE_SIZE,
                            color=ft.Colors.GREY_400,
                            spans=[
                                ft.TextSpan(
                                    "Help on GitHub",
                                    url=REPO_URL,
                                    style=ft.TextStyle(color=CODE_NAME_COLOR),
                                )
                            ],
                        ),
                    ),
                ],
            ),
        )

        right = ft.Container(
            expand=True,
            padding=RIGHT_PANE_PADDING,
            content=ft.Column(
                expand=True,
                spacing=10,
                # Without STRETCH a Column sizes each child to its own content,
                # so the output panel drew as a narrow rectangle instead of
                # filling the width.
                horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
                controls=[
                    self._header,
                    self._needs,
                    spaced_row(
                        [
                            self._check_button,
                            self._install_button,
                            self._uninstall_button,
                            ft.Container(content=self._requirements, expand=True),
                        ],
                        spacing=8,
                    ),
                    # No box anywhere on this page. The CONFIG block is marked
                    # off by a rule above and below it, which says where the
                    # script's settings begin and end without drawing a frame
                    # around dense monospace.
                    spaced_rule(),
                    section_heading("Settings"),
                    ft.Container(expand=3, content=self._form),
                    spaced_rule(),
                    spaced_row(
                        [
                            self._run_button,
                            self._stop_button,
                            ft.Container(content=self._status, expand=True),
                        ]
                    ),
                    ft.Container(
                        expand=2,
                        padding=ft.Padding.only(top=4),
                        # Selection belongs to the area, not the lines: with one
                        # Text per line, per-control selection would stop at the
                        # end of whichever line you started in.
                        content=ft.SelectionArea(content=self._output_list),
                    ),
                    ft.Container(padding=ft.Padding.only(top=4), content=self._input),
                ],
            ),
        )

        self.page.add(ft.Row(expand=True, spacing=0, controls=[rail, right]))
        # Flet 0.85 registers a FilePicker as a service, and only after the page
        # has content, so the registry's update reaches the frontend.
        self.page._services.register_service(self.file_picker)  # type: ignore[attr-defined]

        if stranded:
            self._set_status(f"Cleaned up {stranded} leftover run file(s).")
        self.page.update()

    # ----- the script rail --------------------------------------------------

    def _load_scripts(self) -> None:
        """The scripts to list: every one in the folder that says `GUI = True`.

        Which scripts appear is decided by the scripts, not by this file, so
        adding one to the window is a line in the script rather than a change
        here.

        Two filters, and they answer different questions. `discover()` drops what
        the AUTHOR marked `GUI = False`, which the app never shows anywhere. The
        prefs set drops what THIS USER took off the rail, which the Scripts
        dialog still lists so it can be put back."""
        hidden = prefs.hidden()
        self.scripts = [s for s in catalog.discover() if s.path.name not in hidden]
        if self.scripts:
            _fill(self._rail_list, [self._tile(s) for s in self.scripts])
        else:
            _fill(
                self._rail_list,
                [
                    ft.Text(
                        "No scripts found.",
                        size=STATUS_TEXT_SIZE,
                        italic=True,
                        color=ft.Colors.GREY_500,
                    )
                ],
            )

    def _tile(self, script: catalog.Script) -> ft.Control:
        """One clickable script tile: its filename, and its own one-line
        description from the docstring."""
        active = self.selected is not None and self.selected.path == script.path
        return ft.Container(
            on_click=lambda _e, s=script: self._select(s),
            bgcolor=ACTIVE_BG if active else None,
            border_radius=6,
            padding=ft.Padding.symmetric(horizontal=10, vertical=8),
            ink=True,
            content=ft.Column(
                spacing=2,
                controls=[
                    ft.Text(script.title, size=TILE_TITLE_SIZE, weight=ft.FontWeight.BOLD),
                    ft.Text(
                        script.subtitle,
                        size=TILE_SUBTITLE_SIZE,
                        color=ft.Colors.GREY_400,
                        max_lines=3,
                    ),
                ],
            ),
        )

    def _on_refresh(self, _e: ft.Event) -> None:
        """Rescan the folder. The rail is built once at startup, so this is how
        a script added since then appears."""
        self._reload_rail()
        self._set_status(f"{len(self.scripts)} script(s).")
        self.page.update()

    # ----- installs ---------------------------------------------------------

    def _on_check(self, _e: ft.Event) -> None:
        self.page.run_task(self._check)

    async def _check(self) -> None:
        """Report which of the selected script's imports are present.

        Read-only: nothing is installed, and `find_spec` answers without
        importing, so checking a heavy package costs nothing."""
        script = self.selected
        if script is None:
            return
        needed = installs.requirements(script)
        if not needed:
            _fill(self._requirements, [self._req_text("Needs nothing installed.", ok=True)])
            self._missing = ()
            self._install_button.disabled = True
            self.page.update()
            return

        self._set_status("Checking...")
        self.page.update()
        present = await installs.installed(tuple(r.module for r in needed))

        parts, missing = [], []
        for req in needed:
            if present.get(req.module):
                parts.append(req.package)
            else:
                parts.append(f"{req.package} MISSING ({req.describe()})")
                if not req.optional:
                    missing.append(req)
        self._missing = tuple(missing)
        _fill(
            self._requirements,
            [self._req_text(" · ".join(parts), ok=not any("MISSING" in p for p in parts))],
        )
        self._install_button.disabled = not self._missing
        self._set_status(
            f"{len(self._missing)} package(s) to install." if self._missing else "All present."
        )
        self.page.update()

    def _req_text(self, value: str, *, ok: bool) -> ft.Text:
        return ft.Text(
            value,
            size=STATUS_TEXT_SIZE,
            color=ft.Colors.GREY_500 if ok else ERROR_COLOR,
        )

    def _on_install(self, _e: ft.Event) -> None:
        self.page.run_task(self._install)

    async def _install(self) -> None:
        """Install the missing required packages, streaming pip into the output
        pane. Never `-U`: this environment is shared, and upgrading something
        another project depends on is how that project breaks."""
        if not self._missing:
            return
        packages = sorted({r.package for r in self._missing})
        self._busy(True)
        self._clear_output()
        self._set_status(f"Installing {', '.join(packages)}...")
        self.page.update()
        code = await installs.pip(["install", *packages], self._on_line)
        self._paint_output()
        self._busy(False)
        self._set_status("Installed." if code == 0 else f"pip exited with code {code}.")
        await self._check()

    def _on_uninstall(self, _e: ft.Event) -> None:
        """Confirm before removing anything, naming exactly what goes and what
        stays.

        Two protections, because this environment is shared with the other
        projects in the folder: a package another listed script also imports is
        never offered, and the dialog says plainly that other projects may be
        using what is left.
        """
        script = self.selected
        if script is None:
            return
        mine = {r.package for r in installs.requirements(script)}
        others: dict[str, list[str]] = {}
        # Deliberately the scripts LISTED in the rail, not every file in the
        # folder. The point of Uninstall is to end up with only what the scripts
        # you actually use require, so hiding the ones you do not use is what
        # makes their dependencies removable. Guarding on the whole folder would
        # mean nothing shared could ever be removed, and the environment could
        # never be slimmed down at all.
        for other in self.scripts:
            if other.path == script.path:
                continue
            for req in installs.requirements(other):
                if req.package in mine:
                    others.setdefault(req.package, []).append(other.title)

        removable = sorted(mine - set(others))
        kept = sorted(others)

        # Which of these another project in the folder declares. Named rather
        # than hinted at: "Epistemon needs this" stops you, "the environment is
        # shared" does not. Empty, and silent, once Automation is installed on
        # its own with no neighbours.
        claimed = installs.declared_by_neighbours(removable)

        rows: list[ft.Control] = [
            ft.Text(
                ("Will be removed: " + ", ".join(removable)) if removable else "Nothing to remove.",
                size=TILE_SUBTITLE_SIZE,
            )
        ]
        for package, projects in claimed.items():
            rows.append(
                ft.Text(
                    f"WARNING  {package} is also declared by {', '.join(projects)}, "
                    "which shares this Python environment.",
                    size=TILE_SUBTITLE_SIZE,
                    color=ERROR_COLOR,
                )
            )
        rows.append(thin_rule())
        if kept:
            rows.append(
                ft.Text(
                    "Kept, still needed by other scripts: "
                    + ", ".join(f"{p} ({', '.join(others[p])})" for p in kept),
                    size=TILE_SUBTITLE_SIZE,
                    color=ft.Colors.GREY_400,
                )
            )

        def _go(_ev) -> None:
            self.page.pop_dialog()
            if removable:
                self.page.run_task(self._uninstall, removable)

        dialog = ft.AlertDialog(
            modal=True,
            scrollable=True,
            title=ft.Text(f"Uninstall for {script.path.name}"),
            content=ft.Container(
                width=680, content=ft.Column(controls=rows, spacing=8, tight=True)
            ),
            actions=[
                ft.Button(content=ft.Text("Cancel"), on_click=lambda _ev: self.page.pop_dialog()),
                ft.Button(content=ft.Text("Uninstall"), on_click=_go, disabled=not removable),
            ],
        )
        self.page.show_dialog(dialog)

    async def _uninstall(self, packages: list[str]) -> None:
        self._busy(True)
        self._clear_output()
        self._set_status(f"Uninstalling {', '.join(packages)}...")
        self.page.update()
        code = await installs.pip(["uninstall", "-y", *packages], self._on_line)
        self._paint_output()
        self._busy(False)
        self._set_status("Uninstalled." if code == 0 else f"pip exited with code {code}.")
        await self._check()

    def _busy(self, busy: bool) -> None:
        """Lock the buttons that must not overlap a pip run or a script run."""
        self._run_button.disabled = busy or self.selected is None
        self._check_button.disabled = busy or self.selected is None
        self._uninstall_button.disabled = busy or self.selected is None
        self._install_button.disabled = busy or not self._missing

    # ----- the info dialog --------------------------------------------------

    def _on_info(self, script: catalog.Script) -> None:
        """Show the script's own docstring: what it does, what it needs
        installed, and where anything it downloads will land.

        Monospace and verbatim, so the indented `Setup:` block keeps its shape
        and a reader sees exactly the text that is in the file. The one line the
        GUI adds is the framing above it: the docstrings were written for
        someone running the script from a terminal, and would otherwise send a
        window user off to make a `.env` file they do not need.
        """
        body = ft.Column(
            spacing=10,
            tight=True,
            controls=[
                ft.Text(
                    "Keys for this app are set in the Keys dialog. The notes below are the "
                    "script's own, and describe running it directly from a terminal.",
                    size=TILE_SUBTITLE_SIZE,
                    color=ft.Colors.GREY_400,
                ),
                thin_rule(),
                ft.Text(
                    script.doc or "(this script has no description)",
                    font_family="Consolas",
                    size=OUTPUT_SIZE,
                    selectable=True,
                ),
            ],
        )
        dialog = ft.AlertDialog(
            modal=True,
            scrollable=True,
            title=ft.Text(script.path.name),
            content=ft.Container(width=720, content=body),
            actions=[
                ft.Button(content=ft.Text("Close"), on_click=lambda _ev: self.page.pop_dialog())
            ],
        )
        self.page.show_dialog(dialog)

    # ----- choosing which scripts are listed --------------------------------

    def _on_add_scripts(self, _e: ft.Event) -> None:
        """Every script the window may show, with a checkbox: ticked means it
        appears in the list on the left.

        The tick is a preference in `prefs.py`, NOT the script's `GUI` line. It
        used to write that line, which meant unticking a tile edited a
        version-controlled file, and a checkout ended up with a pile of modified
        scripts. It also left `GUI = False` meaning two different things.

        Scripts marked `GUI = False` are absent from this dialog entirely, which
        is the author's decision and not the user's to reverse from here. Nothing
        is created and nothing is deleted; unticking only takes a script off the
        rail, reversibly.
        """
        found = catalog.discover()
        hidden = prefs.hidden()
        boxes: dict[Path, ft.Checkbox] = {}

        def _toggle_all(ev: ft.Event) -> None:
            """Tick or untick every row at once, from the box at the top."""
            wanted = bool(ev.control.value)
            for one in boxes.values():
                one.value = wanted
            self.page.update()

        select_all = ft.Checkbox(
            value=not hidden,
            label="Select all",
            on_change=_toggle_all,
        )
        rows: list[ft.Control] = [
            ft.Text(
                "Ticked scripts appear in the list on the left. Unticking one removes it "
                "from the list; the script file itself is never changed.",
                size=TILE_SUBTITLE_SIZE,
                color=ft.Colors.GREY_400,
            ),
            thin_rule(),
            select_all,
            thin_rule(),
        ]
        for script in found:
            box = ft.Checkbox(value=script.path.name not in hidden)
            boxes[script.path] = box
            rows.append(
                ft.Row(
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    spacing=8,
                    controls=[
                        box,
                        ft.Container(
                            expand=True,
                            content=ft.Column(
                                spacing=0,
                                controls=[
                                    ft.Text(script.title, size=TILE_TITLE_SIZE),
                                    ft.Text(
                                        script.subtitle,
                                        size=TILE_SUBTITLE_SIZE,
                                        color=ft.Colors.GREY_400,
                                    ),
                                ],
                            ),
                        ),
                    ],
                )
            )

        # The foot of this dialog is where a missing script sends you: it lists
        # everything on this machine, so anything not here has to come from the
        # repo. `TextSpan(url=...)` opens the browser natively, which avoids
        # `page.launch_url` (deprecated in 0.90) and needs no service.
        rows.append(thin_rule())
        rows.append(
            ft.Text(
                size=TILE_SUBTITLE_SIZE,
                color=ft.Colors.GREY_400,
                spans=[
                    ft.TextSpan(
                        "Check for new scripts and updates on GitHub",
                        url=REPO_URL,
                        style=ft.TextStyle(color=CODE_NAME_COLOR),
                    )
                ],
            )
        )

        def _save(_ev) -> None:
            wanted_hidden = {script.path.name for script in found if not boxes[script.path].value}
            changed = len(wanted_hidden ^ hidden)
            self.page.pop_dialog()
            try:
                prefs.set_hidden(wanted_hidden)
            except OSError as exc:
                # Say so rather than swallow it: a preference that silently fails
                # to save undoes itself on the next launch, which reads as the
                # app forgetting rather than as an error.
                self._set_status(f"Could not save the choice: {exc}")
                self.page.update()
                return
            self._reload_rail()
            self._set_status(f"{changed} script(s) changed." if changed else "No changes.")
            self.page.update()

        dialog = ft.AlertDialog(
            modal=True,
            scrollable=True,
            title=ft.Text("Scripts"),
            content=ft.Container(
                width=640, content=ft.Column(controls=rows, spacing=6, tight=True)
            ),
            actions=[
                ft.Button(content=ft.Text("Cancel"), on_click=lambda _ev: self.page.pop_dialog()),
                ft.Button(content=ft.Text("Save"), on_click=_save),
            ],
        )
        self.page.show_dialog(dialog)

    def _reload_rail(self) -> None:
        """Rebuild the rail after the shown set changed, keeping the open script
        selected if it is still listed and clearing the page if it is not."""
        previous = self.selected.path if self.selected else None
        self._load_scripts()
        still_there = next((s for s in self.scripts if s.path == previous), None)
        if still_there is not None:
            self._select(still_there)
        elif previous is not None:
            self.selected = None
            _fill(self._header, [])
            _fill(self._needs, [])
            _fill(self._form, [])
            _fill(self._requirements, [])
            self._missing = ()
            self._run_button.disabled = True
            self._check_button.disabled = True
            self._install_button.disabled = True
            self._uninstall_button.disabled = True

    # ----- keys -------------------------------------------------------------

    def _credential_names(self) -> list[str]:
        """Every credential the scripts read, across the whole folder.

        `discover_all` on purpose: a script marked `GUI = False` is unlisted
        because it is not ready to be shown, not because its credentials stopped
        existing. The file is still in the folder and still runs from a terminal,
        so its keys belong in the dialog. Filtering here also disagreed with
        `clear_keys.py`, which clears the unfiltered set, so the uninstaller
        would have removed keys this dialog never showed.
        """
        found: set[str] = set()
        for script in catalog.discover_all():
            found.update(script.env_vars)
        return sorted(found)

    def _needs_line(self, script: catalog.Script) -> ft.Control:
        """One line naming the credentials this script reads. Names only.

        No verdict on whether each is present: the Keys dialog shows that by
        whether the box has anything in it, which is one place to look rather
        than two that can disagree."""
        if not script.env_vars:
            # No full stop: the populated form is "Keys: OPENAI_API_KEY", and one
            # state ending in a stop while the other does not is the only real
            # inconsistency between them.
            return ft.Text("Keys: none", size=STATUS_TEXT_SIZE, color=ft.Colors.GREY_500)
        return ft.Text(
            "Keys: " + ", ".join(script.env_vars),
            size=STATUS_TEXT_SIZE,
            color=ft.Colors.GREY_500,
        )

    def _on_keys(self, _e: ft.Event) -> None:
        """The Keys dialog: one row per credential the scripts read.

        Every box shows what is stored, so a filled box means set and an empty
        box means not set - no separate status column saying the same thing.
        Secrets are masked with a reveal button; addresses are not secrets, so
        they show plainly. Saving writes exactly what is in each box, which
        makes clearing a box and saving the way to remove a credential.
        """
        names = self._credential_names()
        inputs: dict[str, ft.TextField] = {}
        rows: list[ft.Control] = [
            ft.Text(
                "Stored in Windows Credential Manager, not in a file. These are what the "
                "scripts run with. Clear a box and save to remove one.",
                size=TILE_SUBTITLE_SIZE,
                color=ft.Colors.GREY_400,
            ),
            thin_rule(),
        ]

        for name in names:
            secret = keys.is_secret(name)
            field = ft.TextField(
                value=keys.get(name),
                password=secret,
                can_reveal_password=secret,
                dense=True,
            )
            apply_input_box(field)
            inputs[name] = field

            def _clear(_ev, n=name, f=field) -> None:
                """Remove this credential immediately, without waiting for Save.
                Emptying the box alone would do it too, but only on Save."""
                keys.clear(n)
                f.value = ""
                self.page.update()

            rows.append(
                ft.Row(
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    spacing=6,
                    controls=[
                        ft.Container(width=230, content=code_text(name)),
                        ft.Container(expand=True, content=field),
                        ft.IconButton(
                            icon=ft.Icons.DELETE_OUTLINE,
                            tooltip=f"Remove {name} from the credential store",
                            on_click=_clear,
                        ),
                    ],
                )
            )

        def _save(_ev) -> None:
            saved = 0
            for name, field in inputs.items():
                typed = (field.value or "").strip()
                if typed == keys.get(name):
                    continue
                keys.save(name, typed)
                saved += 1
            self.page.pop_dialog()
            self._set_status(f"Saved {saved} credential(s)." if saved else "No changes.")
            self.page.update()

        dialog = ft.AlertDialog(
            modal=True,
            scrollable=True,
            title=ft.Text("Keys"),
            content=ft.Container(
                width=760, content=ft.Column(controls=rows, spacing=8, tight=True)
            ),
            actions=[
                ft.Button(content=ft.Text("Cancel"), on_click=lambda _ev: self.page.pop_dialog()),
                ft.Button(content=ft.Text("Save"), on_click=_save),
            ],
        )
        self.page.show_dialog(dialog)

    # ----- the CONFIG form --------------------------------------------------

    def _select(self, script: catalog.Script) -> None:
        """Show a script. Re-selecting the same one rebuilds the form from the
        file, which is also how you discard edits."""
        if self._run is not None:
            self._set_status("A script is still running. Stop it first.")
            self.page.update()
            return

        self.selected = script
        self._inputs = {}
        self._errors = {}

        _fill(
            self._header,
            [
                # Filename, info icon, then the one-line description, all on one
                # line: the description reads as the title's continuation, so it
                # belongs beside it rather than under it.
                ft.Row(
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    spacing=4,
                    controls=[
                        ft.Text(script.path.name, size=PANEL_TITLE_SIZE, weight=ft.FontWeight.BOLD),
                        ft.IconButton(
                            icon=ft.Icons.INFO_OUTLINE,
                            icon_size=18,
                            tooltip="What this script does",
                            on_click=lambda _e, s=script: self._on_info(s),
                        ),
                        ft.Container(
                            expand=True,
                            padding=ft.Padding.only(left=4),
                            content=ft.Text(
                                script.subtitle, size=SUBTITLE_SIZE, color=ft.Colors.GREY_400
                            ),
                        ),
                    ],
                ),
            ],
        )

        _fill(self._needs, [self._needs_line(script)])

        # No `# ===== CONFIG =====` lines here: the rules above and below the
        # form already say where the block starts and stops, and the markers
        # were furniture repeating what the layout shows.
        rows: list[ft.Control] = []
        for field in script.fields:
            rows.extend(self._field_rows(script, field))
        _fill(self._form, rows)

        _fill(self._rail_list, [self._tile(s) for s in self.scripts])
        # A check belongs to one script, so drop the previous answer rather than
        # letting it enable Install for a script it was never about.
        self._missing = ()
        _fill(self._requirements, [])
        self._check_button.disabled = False
        self._uninstall_button.disabled = False
        self._install_button.disabled = True
        self._run_button.disabled = False
        self._clear_output()
        self._set_status(f"{len(script.fields)} setting(s). Edit and press Run.", idle=True)
        self.page.update()

    def _field_rows(self, script: catalog.Script, field: catalog.Field) -> list[ft.Control]:
        """One CONFIG line: `NAME = [value]  comment`, plus a hidden error line
        underneath that only fills in when the value will not parse."""
        control = self._input_for(script, field)
        self._inputs[field.name] = control

        value_cell: ft.Control = control
        if field.kind in ("folder", "open_file", "save_file"):
            value_cell = ft.Row(
                spacing=4,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                controls=[
                    ft.Container(content=control, expand=True),
                    ft.IconButton(
                        icon=ft.Icons.FOLDER_OPEN,
                        tooltip="Browse",
                        on_click=lambda _e, f=field: self.page.run_task(self._browse, f),
                    ),
                ],
            )

        comment: ft.Control = ft.Container()
        if field.comment:
            # No `#` in front. In the file it marks where the comment starts;
            # here the column and the colour already say that, so it is noise.
            comment = code_text(field.comment, color=CODE_COMMENT_COLOR)

        error = ft.Text("", size=ERROR_SIZE, color=ERROR_COLOR, visible=False)
        self._errors[field.name] = error

        # A one-line box is CENTRED against, not measured from. Any top padding
        # is a guess about how much space Flutter leaves around the text inside
        # the box, and it was always out by a pixel or two. A multiline box is
        # taller than its first line, so those rows do align to the top, with
        # `INPUT_TEXT_TOP` putting the name level with line one.
        tall = field.kind == "long_text"
        top = INPUT_TEXT_TOP if tall else 0
        return [
            ft.Row(
                vertical_alignment=(
                    ft.CrossAxisAlignment.START if tall else ft.CrossAxisAlignment.CENTER
                ),
                spacing=6,
                controls=[
                    ft.Container(
                        width=NAME_COLUMN_WIDTH,
                        padding=ft.Padding.only(top=top),
                        content=code_text(field.name, color=CODE_NAME_COLOR),
                    ),
                    ft.Container(
                        padding=ft.Padding.only(top=top),
                        content=code_text("="),
                    ),
                    ft.Container(expand=3, content=value_cell),
                    ft.Container(
                        expand=2,
                        padding=ft.Padding.only(top=top, left=6),
                        content=comment,
                    ),
                ],
            ),
            ft.Container(padding=ft.Padding.only(left=NAME_COLUMN_WIDTH + 12), content=error),
        ]

    def _input_for(self, script: catalog.Script, field: catalog.Field) -> ft.Control:
        """The widget for one field. Whatever the widget, its value is the
        Python literal as it would be written in the file."""
        if field.kind == "bool":
            control: ft.Control = ft.Dropdown(
                value=field.literal,
                options=[ft.DropdownOption(key=v, text=v) for v in ("True", "False")],
            )
        elif field.kind == "choice":
            options = catalog.choices_for(script.stem, field.name)
            # Keep an unexpected current value selectable rather than silently
            # replacing it: the file is the authority, not this table.
            if field.literal not in options:
                options = (field.literal, *options)
            control = ft.Dropdown(
                value=field.literal,
                options=[ft.DropdownOption(key=v, text=v) for v in options],
            )
        elif field.kind == "long_text":
            control = ft.TextField(
                value=field.literal,
                multiline=True,
                min_lines=2,
                max_lines=8,
                dense=True,
            )
        else:
            control = ft.TextField(value=field.literal, dense=True)
        return apply_input_box(control)

    def _value_of(self, name: str) -> str:
        control = self._inputs.get(name)
        return (getattr(control, "value", "") or "").strip()

    def _values(self) -> dict[str, str]:
        return {
            f.name: self._value_of(f.name) for f in (self.selected.fields if self.selected else ())
        }

    async def _browse(self, field: catalog.Field) -> None:
        """Open the OS picker for a path field and write the result back as a
        Python literal, in the `r"..."` style the scripts already use."""
        start = _existing_dir(self._value_of(field.name))
        chosen: str | None = None
        if field.kind == "folder":
            chosen = await self.file_picker.get_directory_path(
                dialog_title=f"{field.name}", initial_directory=start
            )
        elif field.kind == "save_file":
            chosen = await self.file_picker.save_file(
                dialog_title=f"{field.name}",
                file_name=_basename(self._value_of(field.name)),
                initial_directory=start,
            )
        else:
            picked = await self.file_picker.pick_files(
                dialog_title=f"{field.name}", initial_directory=start, allow_multiple=False
            )
            if picked:
                chosen = picked[0].path
        if not chosen:
            return
        control = self._inputs.get(field.name)
        if control is not None:
            control.value = _path_literal(chosen)
            self.page.update()

    # ----- running ----------------------------------------------------------

    def _on_run(self, _e: ft.Event) -> None:
        script = self.selected
        if script is None or self._run is not None:
            return

        values = self._values()
        errors = runner.validate(script, values)
        for name, error in self._errors.items():
            error.value = errors.get(name, "")
            error.visible = name in errors
        if errors:
            self._set_status(f"{len(errors)} setting(s) need fixing.")
            self.page.update()
            return

        absent = [name for name in script.env_vars if not keys.is_set(name)]
        if absent:
            self._ask_about_keys(script, values, absent)
            return

        self._start(script, values)

    def _ask_about_keys(
        self, script: catalog.Script, values: dict[str, str], absent: list[str]
    ) -> None:
        """Say a key is missing BEFORE the script runs, rather than after.

        Without this the script starts, fails, and prints its own "put it in a
        .env file" message into the output pane, which sends someone using the
        window off to make a file they do not have.

        It asks rather than blocks, because the Keys dialog is not the only way
        a key can reach a script: someone running from a terminal has other
        ways, and refusing to start would be wrong for them.
        """

        def _run_anyway(_ev) -> None:
            self.page.pop_dialog()
            self._start(script, values)

        def _open_keys(_ev) -> None:
            self.page.pop_dialog()
            self._on_keys(_ev)

        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("Keys not set"),
            content=ft.Container(
                width=560,
                content=ft.Column(
                    tight=True,
                    spacing=8,
                    controls=[
                        ft.Text(
                            f"{script.path.name} needs " + ", ".join(absent) + ".",
                            size=SUBTITLE_SIZE,
                        ),
                        ft.Text(
                            "Nothing is stored for it in Keys. Add it there, or run anyway if "
                            "this script gets it another way.",
                            size=TILE_SUBTITLE_SIZE,
                            color=ft.Colors.GREY_400,
                        ),
                    ],
                ),
            ),
            actions=[
                ft.Button(content=ft.Text("Cancel"), on_click=lambda _ev: self.page.pop_dialog()),
                ft.Button(content=ft.Text("Run anyway"), on_click=_run_anyway),
                ft.Button(content=ft.Text("Open Keys"), on_click=_open_keys),
            ],
        )
        self.page.show_dialog(dialog)

    def _start(self, script: catalog.Script, values: dict[str, str]) -> None:
        """Launch the script with the form's values. The only path that runs."""
        self._clear_output()
        self._run_button.disabled = True
        self._stop_button.disabled = False
        # Enabled for every run: which scripts ask a question is not knowable
        # without running them, and an unused box costs nothing.
        self._input.disabled = False
        self._input.value = ""
        self._set_status(f"Running {script.path.name}...")
        self.page.update()

        self._run = runner.ScriptRun(
            script=script,
            source=runner.build_source(script, values),
            on_line=self._on_line,
            on_partial=self._on_partial,
            on_done=self._on_done,
            # Credentials go through the environment, never into the twin's
            # source, so nothing secret is ever written to disk.
            env=keys.as_env(script.env_vars),
        )
        self.page.run_task(self._run.start)

    def _on_stop(self, _e: ft.Event) -> None:
        if self._run is not None:
            self._set_status("Stopping...")
            self._run.stop()
            self.page.update()

    def _on_send(self, _e: ft.Event) -> None:
        self.page.run_task(self._send)

    async def _send(self) -> None:
        """Answer a script that is waiting on `input()`, and echo the answer.

        The echo is the GUI's own. A terminal shows what you typed because the
        terminal echoes it; a piped stdin does not, so without this the output
        would hold every question and none of the answers.

        The answer joins the prompt on its own line, the way a terminal shows
        it: `input("You: ")` prints no newline, so that prompt is the pending
        partial, and appending to it gives `You: my answer`. With nothing
        pending, the script asked in some other way, so the answer stands alone
        behind a `>`.
        """
        run = self._run
        text = self._input.value or ""
        if run is None:
            self._set_status("Nothing is running.")
            self.page.update()
            return
        self._input.value = ""
        if await run.send(text):
            self._on_line(f"{self._pending}{text}" if self._pending else f"> {text}")
            self._pending = ""
            self._paint_output()
        else:
            self._set_status("The script is no longer reading input.")
        await self._input.focus()
        self.page.update()

    def _on_line(self, line: str) -> None:
        self._lines.append(line)
        dropped = len(self._lines) - OUTPUT_MAX_LINES
        if dropped > 0:
            del self._lines[:dropped]
            # `_rendered` indexes into `_lines`, so it has to move with the cut.
            self._rendered = max(0, self._rendered - dropped)
        now = time.monotonic()
        if now - self._last_paint >= OUTPUT_REFRESH_SECONDS:
            self._last_paint = now
            self._paint_output()

    def _on_done(self, code: int | None) -> None:
        self._run = None
        self._run_button.disabled = self.selected is None
        self._stop_button.disabled = True
        self._input.disabled = True
        self._input.value = ""
        self._paint_output()
        if code is None:
            self._set_status("Stopped.")
        elif code == 0:
            self._set_status("Finished.")
        else:
            self._set_status(f"Finished with exit code {code}.")
        self.page.update()

    def _on_partial(self, text: str) -> None:
        """Show, or clear, the line the script is still writing.

        Painted immediately, unlike `_on_line`. A prompt is the last thing a
        blocked script sends, so a throttle that skipped this repaint would
        leave the question invisible until the script produced more output,
        which it never will. Cheap regardless: this fires once per chunk read
        and only when the tail actually changed, so it is rarer than per line.
        """
        if text == self._pending:
            return
        self._pending = text
        self._last_paint = time.monotonic()
        self._paint_output()

    def _paint_output(self) -> None:
        """Bring the list of controls level with the buffer.

        Appends only what is new, so a long run does not rebuild the whole
        pane. The pending line is always the last child and is thrown away and
        remade each time, which is also what keeps `auto_scroll` following a
        script that is printing without newlines.
        """
        controls = self._output_list.controls
        if self._pending_control is not None:
            controls.pop()
            self._pending_control = None
        for line in self._lines[self._rendered :]:
            controls.append(_output_line(line))
        self._rendered = len(self._lines)
        excess = len(controls) - OUTPUT_MAX_LINES
        if excess > 0:
            del controls[:excess]
        if self._pending:
            self._pending_control = _output_line(self._pending)
            controls.append(self._pending_control)
        self.page.update()

    def _clear_output(self) -> None:
        self._lines = []
        self._pending = ""
        self._rendered = 0
        self._pending_control = None
        self._output_list.controls.clear()

    def _set_status(self, text: str, *, idle: bool = False) -> None:
        self._status.value = text
        apply_status_style(self._status, idle=idle)


# ----- small helpers -------------------------------------------------------


def _output_line(text: str) -> ft.Text:
    """One line of a run's output.

    A blank line is drawn as a space: an empty `Text` collapses to no height,
    and a script's blank lines are how its output is paragraphed.
    """
    return ft.Text(text or " ", font_family="Consolas", size=OUTPUT_SIZE)


def _fill(container: ft.Column, controls: list[ft.Control]) -> None:
    """Replace a Column's children IN PLACE.

    `container.controls = [...]` rebinds the list, and Flet 0.85 does not
    reliably act on that once the control is already on the page: the first
    build of this window drew an empty script rail for exactly that reason.
    Clearing and extending mutates the list Flet is already watching, so the
    change reaches the window.
    """
    container.controls.clear()
    container.controls.extend(controls)


def _path_literal(value: str) -> str:
    """A filesystem path as the CONFIG blocks write them: `r"C:\\path\\to"`.

    Falls back to `repr` for the two cases a raw string cannot hold: a path
    containing a double quote, and one ending in a backslash (which would
    escape the closing quote even in a raw string).
    """
    if '"' not in value and not value.endswith("\\"):
        return f'r"{value}"'
    return repr(value)


def _literal_text(text: str) -> str:
    """The plain string a field's literal holds, or "" if it is not a string."""
    try:
        parsed = ast.literal_eval(text)
    except (ValueError, SyntaxError):
        return ""
    return parsed if isinstance(parsed, str) else ""


def _existing_dir(literal: str) -> str | None:
    """Where a Browse dialog should open: the field's current folder if it
    exists, otherwise let the OS decide."""
    raw = _literal_text(literal)
    if not raw:
        return None
    path = Path(raw)
    candidate = path if path.is_dir() else path.parent
    return str(candidate) if candidate.is_dir() else None


def _basename(literal: str) -> str | None:
    """The filename part of a path field, to pre-fill a Save dialog."""
    raw = _literal_text(literal)
    return Path(raw).name if raw else None


# ----- entry point ---------------------------------------------------------


def _arm_close_watchdog() -> None:
    """Force-exit shortly after the window is asked to close.

    On Windows, Flet/asyncio's teardown after a window close can hang, so
    `ft.run()` never returns and the process lingers. Started from a shortcut
    with `pythonw.exe` that zombie is invisible, so it would pile up unnoticed.
    A daemon thread (so it can never itself block shutdown) hard-exits if the
    normal close has not already killed us.
    """

    def _watchdog() -> None:
        time.sleep(2.0)
        os._exit(0)

    threading.Thread(target=_watchdog, name="automation-gui-close", daemon=True).start()


async def _page_factory(page: ft.Page) -> None:
    async def _on_window_event(e) -> None:
        etype = getattr(e, "type", None)
        # Compare the string value so this holds whether `type` is a str-enum,
        # a plain enum, or a raw string.
        if getattr(etype, "value", etype) != "close":
            return
        _arm_close_watchdog()
        # Closing must never raise in the user's face, and a Flet API change
        # here must never stop the window from closing.
        with contextlib.suppress(Exception):
            await page.window.destroy()

    # Installing the hook is best-effort for the same reason: a Flet change
    # must not stop the app from launching.
    with contextlib.suppress(Exception):
        page.window.prevent_close = True
        page.window.on_event = _on_window_event

    AutomationGui(page).build()


def main() -> None:
    """Entry point for `python gui/app.py`."""
    # Inside a packaged bundle this process doubles as the script runner; the
    # call returns immediately in every normal launch.
    runner.maybe_run_child()
    try:
        ft.run(_page_factory)
    finally:
        # Same Windows close-hang net as the watchdog above, for the path where
        # ft.run() does return but interpreter shutdown then blocks joining a
        # thread Flet left running.
        os._exit(0)


if __name__ == "__main__":
    main()
