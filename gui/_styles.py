"""Shared visual constants for the Automation GUI.

A trimmed copy of Epistemon's `gui/_styles.py`, kept so this app and its two
sibling Flet apps read as one family: black page, thin grey frames, one status
line rule. Only what this GUI actually uses is here - reach for the Epistemon
original if a panel ever needs something richer.

Written against the Flet 0.85 API (`ft.Border.all`, `ft.Padding.only`,
`Dropdown.on_select`). It is not compatible either side of that line, so pin
`flet>=0.85,<0.86` whenever this folder gains a pyproject.
"""

from __future__ import annotations

import flet as ft

# ---- surfaces -------------------------------------------------------------

PAGE_BG = ft.Colors.BLACK
"""The page background. Matches the dark Material 3 surface the siblings use."""

PANEL_BG = ft.Colors.BLACK
"""Panel interior. Same as the page: only the grey frame delimits a panel."""

RAIL_BG = ft.Colors.GREY_900
"""A step lighter than the page, for the left script rail, so it lifts off the
background without needing a border of its own."""

FRAME_BORDER_COLOR = ft.Colors.GREY_700
"""Border colour for panel frames, input boxes and dividers."""

RAIL_BUTTON_BG = ft.Colors.BLACK
"""Background of a full-width button in the rail (Keys). Darker than the rail
itself, so the button reads as a recess rather than a raised Material chip."""

ACTIVE_BG = ft.Colors.BLUE_GREY_900
"""Background of the selected script tile. It has to sit above the rail's
GREY_900 without the selected tile shouting louder than the panel it labels.
Walked down twice: BLUE_GREY_700 read as a highlighter pen, BLUE_GREY_800 was
still too loud. This is the same lightness step as the rail, distinguished by
its blue cast rather than by brightness."""

ERROR_COLOR = ft.Colors.RED_300
"""A field whose value is not valid Python. Bright enough to find, not so
saturated it reads as a crash."""

PANEL_RADIUS = 8
"""Corner radius for column-level panels. Inner boxes stay tighter (4) so the
nesting reads as hierarchy rather than a doubled border."""


# ---- the rendered CONFIG block --------------------------------------------
# The right-hand page is meant to read as the script's own source, so every
# part of it is monospace and the colours mirror what an editor would do:
# constant names stand out, comments recede, the marker lines are furniture.

CODE_FONT = "Consolas"
"""Monospace family for everything in the rendered CONFIG block and the output
pane. Consolas ships with Windows; Flet falls back on its own monospace
elsewhere."""

CODE_SIZE = 15
"""Size of the rendered CONFIG lines and their input fields. One step below the
prose size, because a wall of code reads better slightly tighter."""

CODE_NAME_COLOR = ft.Colors.LIGHT_BLUE_200
"""Constant names on the left of the `=`."""

CODE_COMMENT_COLOR = ft.Colors.GREY_500
"""The script's own trailing comment, carried through as the field's help text.
Dimmer than the value it explains."""

# No CODE_MARKER_COLOR: the `# ==== CONFIG ====` lines were drawn for a while so
# the page looked like the file, then dropped once rules bracketed the block.
# They carried no information the layout was not already showing.

OUTPUT_SIZE = 14
"""Output pane text. Smaller than the form: it is a transcript, not something
you edit."""

INPUT_CONTENT_PADDING = 10
"""Space between an input box's border and the text inside it. Set explicitly
rather than left to Flutter's default, because the CONFIG form has to put a
constant name and a comment on the same visual line as the value, and it can
only do that if it knows where the value's text sits."""

INPUT_TEXT_TOP = INPUT_CONTENT_PADDING + 1
"""Top padding for text that must line up with text INSIDE an input box: the
content padding plus the box's one-pixel border. Use this rather than a
hand-tuned number, so the two move together."""


# ---- text sizes -----------------------------------------------------------
# Every size in the app is named here, so "make the text bigger" is a change in
# one file rather than a hunt through app.py. The whole set was raised by 2 on
# 2026-08-17; the relative steps between them are what matter, so move them
# together if they move again.

PANEL_TITLE_SIZE = 19
"""A panel or column title: "Scripts", and the selected script's filename."""

TILE_TITLE_SIZE = 16
"""A script tile's name in the rail."""

TILE_SUBTITLE_SIZE = 13
"""A script tile's one-line description, under its name."""

SUBTITLE_SIZE = 14
"""The selected script's description, under its filename."""

ERROR_SIZE = 13
"""The message under a field whose value will not parse."""


# ---- the status line ------------------------------------------------------
# One line per screen reporting what just happened. Same rule as the siblings:
# an idle line is italic and a step dimmer because it is a PLACEHOLDER, a real
# message is upright at full weight. Build with `status_line`, transition with
# `apply_status_style`, so the two halves cannot drift apart.

IDLE_STATUS = "No activity yet."
STATUS_TEXT_SIZE = 14
STATUS_COLOR = ft.Colors.GREY_400
STATUS_IDLE_COLOR = ft.Colors.GREY_500


def status_line(value: str = "", *, idle: bool = False) -> ft.Text:
    """The app-wide status line. `idle=True` starts it on a placeholder."""
    return ft.Text(
        value,
        size=STATUS_TEXT_SIZE,
        italic=idle,
        color=STATUS_IDLE_COLOR if idle else STATUS_COLOR,
    )


def apply_status_style(control: ft.Text, *, idle: bool) -> None:
    """Re-style an existing status line as idle or live, in place. Does NOT
    touch `value` - the caller owns the text."""
    control.italic = idle
    control.color = STATUS_IDLE_COLOR if idle else STATUS_COLOR


# ---- building blocks ------------------------------------------------------


def apply_input_box(control: ft.Control) -> ft.Control:
    """Give a `TextField` / `Dropdown` the app-standard outlined grey box, and
    the monospace code style the CONFIG form wants.

    Without it a bare Flet `TextField` draws an OUTLINE border with no colour
    (invisible until focus) and a `Dropdown` no border at all, so both render
    borderless on this dark theme. Fills only unset properties, so a
    self-styled control keeps its look. Returns the control for chaining.
    """
    if isinstance(control, ft.TextField | ft.Dropdown):
        if control.border is None:
            control.border = ft.InputBorder.OUTLINE
        if control.border_color is None:
            control.border_color = FRAME_BORDER_COLOR
        if control.bgcolor is None:
            control.bgcolor = PANEL_BG
        if control.text_style is None:
            control.text_style = ft.TextStyle(font_family=CODE_FONT, size=CODE_SIZE)
        if control.content_padding is None:
            control.content_padding = ft.Padding.symmetric(
                vertical=INPUT_CONTENT_PADDING, horizontal=INPUT_CONTENT_PADDING
            )
    return control


def code_text(value: str, *, color: str | None = None, size: int | None = None) -> ft.Text:
    """A monospace run of text at the CONFIG form's size. Used for constant
    names, `=` signs, comments and marker lines."""
    return ft.Text(
        value,
        font_family=CODE_FONT,
        size=size or CODE_SIZE,
        color=color,
        selectable=True,
    )


def panel_title(text: str) -> ft.Text:
    """The title at the top of a panel or column - `PANEL_TITLE_SIZE`, bold."""
    return ft.Text(text, size=PANEL_TITLE_SIZE, weight=ft.FontWeight.BOLD)


# No `panel_box` here on purpose. The app was drawing framed panels around the
# CONFIG block and the output pane, and a box around dense monospace reads as
# clutter. Sections are marked off with `thin_rule()` above and below instead.
# `FRAME_BORDER_COLOR` is still the input-box border, via `apply_input_box`.


SECTION_TITLE_SIZE = 15
"""Size of a section heading inside the page ("Settings"). Bold, and above the
14 of the form captions it heads, but below the 19 of the page title, so the
three levels read as a hierarchy."""


SECTION_TITLE_GAP = 10
"""Air under a section heading, on top of the column's own spacing, so the first
row of the section does not sit tight against the words that head it."""


def section_title(text: str) -> ft.Text:
    """A section heading within the page - bold, `SECTION_TITLE_SIZE`. Sits
    under the rule that opens the section."""
    return ft.Text(text, size=SECTION_TITLE_SIZE, weight=ft.FontWeight.BOLD)


def section_heading(text: str) -> ft.Container:
    """A `section_title` with `SECTION_TITLE_GAP` of air beneath it. Use this in
    the page; the bare title is the primitive."""
    return ft.Container(
        content=section_title(text),
        padding=ft.Padding.only(bottom=SECTION_TITLE_GAP),
    )


SECTION_GAP = 12
"""Vertical breathing room above and below a section boundary - the rules that
bracket the CONFIG block, and the button rows either side of it. One value, so
the page keeps an even rhythm down its length."""


def spaced_rule() -> ft.Container:
    """A `thin_rule` with `SECTION_GAP` of air above and below it. Use this for
    a boundary between sections; the bare `thin_rule` is for a rule that has to
    sit tight against its content, like the one under a panel title."""
    return ft.Container(
        content=thin_rule(),
        padding=ft.Padding.symmetric(vertical=SECTION_GAP),
    )


def spaced_row(controls: list[ft.Control], *, spacing: int = 10) -> ft.Container:
    """A row of controls with the same `SECTION_GAP` of air above and below, so
    a button row sits in the page's rhythm rather than crowding the rule next to
    it."""
    return ft.Container(
        padding=ft.Padding.symmetric(vertical=SECTION_GAP),
        content=ft.Row(
            controls=controls,
            spacing=spacing,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ),
    )


def thin_rule() -> ft.Divider:
    """A subtle rule within a panel - 1px GREY_600, brighter than Flet's
    near-invisible default. Fresh instance per call: a control cannot be shared
    across the tree."""
    return ft.Divider(height=1, thickness=1, color=ft.Colors.GREY_600)
