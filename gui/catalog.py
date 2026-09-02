"""Find the runnable scripts in `Automation/` and read their CONFIG blocks.

NOTHING HERE WRITES TO A SCRIPT. This module only reads, which is what the
README promises the app does. It once had a `set_shown` that rewrote a script's
`GUI` line when a tile was unticked, and that was wrong twice over: it edited a
distributed, version-controlled file to record one user's preference, and it
overloaded the author's "not ready" flag with the user's "not on my rail". The
user's choice now lives in `prefs.py`; `GUI` means only what its author meant.

Everything the GUI shows comes from the file as it already stands:

  - which scripts exist        the `*.py` files in the parent folder
  - which ones the GUI lists   those with a `# ==== CONFIG ====` block AND a
                               `main()`, which is what "runnable, and it has
                               settings" means in structural terms
  - the tile title             the filename
  - the tile subtitle          the docstring's first line, after the " - "
  - the fields                 the module-level assignments inside the block
  - each field's help text     that line's own trailing comment

So adding a script to the folder adds a tile, and removing one removes it.
There is no list to maintain and no per-script schema.

Two small hand-written tables live at the bottom, `_CHOICES` and
`_PATH_KIND_OVERRIDES`. They exist because a few facts genuinely are not in
the source in machine-readable form: which strings a field accepts, and
whether an ambiguous path means a file or a folder. Both are documented where
they are declared.
"""

from __future__ import annotations

import ast
import io
import re
import tokenize
from dataclasses import dataclass
from pathlib import Path

AUTOMATION_DIR = Path(__file__).resolve().parent.parent
"""The folder holding the scripts - the parent of this `gui/` folder."""

# The block delimiters every script already uses, e.g.
#   # ================= CONFIG - edit these, then run =================
#   # ================================================================
# Matched loosely (any run of "=") so a script with a slightly different rule
# length still parses.
_CONFIG_START = re.compile(r"^#\s*=+\s*CONFIG\b", re.IGNORECASE)
_CONFIG_END = re.compile(r"^#\s*=+\s*$")


@dataclass(frozen=True)
class Field:
    """One assignment inside a CONFIG block.

    `literal` is the value's source text EXACTLY as written in the file,
    quotes, `r` prefix and all. That is what the form shows and what the user
    edits, which is why there is no parsed `value` here: the literal is the
    single representation, and it is turned back into a Python object only
    when the run is validated.

    The four position numbers span the VALUE only, not the whole line, so
    substituting a new literal leaves the name, the `=` and the trailing
    comment untouched. `col_offset` and `end_col_offset` are UTF-8 byte
    offsets into their line, as `ast` reports them.
    """

    name: str
    literal: str
    comment: str
    kind: str
    lineno: int
    col_offset: int
    end_lineno: int
    end_col_offset: int


@dataclass(frozen=True)
class Script:
    """One script the GUI can run."""

    path: Path
    title: str
    subtitle: str
    doc: str
    fields: tuple[Field, ...]
    env_vars: tuple[str, ...]
    shown: bool
    source: str

    @property
    def stem(self) -> str:
        return self.path.stem


def discover_all(folder: Path | None = None) -> list[Script]:
    """Every runnable script in `folder`, alphabetically, `GUI` ignored.

    For the things that are true of a script whether or not the window lists it.
    Credentials are the case that matters: a script the author marked `GUI =
    False` still runs from a terminal and still reads its keys, so the keys
    dialog and `clear_keys.py` both walk this list. When they disagreed, the
    uninstaller removed keys the dialog had never shown.

    Skips names starting with `_`, which covers both private helpers and the
    `_gui_run_*.py` twins this GUI writes while a script is running - without
    that, a run in progress would briefly add a tile for itself.

    A file that cannot be read or parsed is skipped rather than raised on: one
    broken script must never stop the whole app from listing the others.
    """
    base = folder or AUTOMATION_DIR
    scripts: list[Script] = []
    for path in sorted(base.glob("*.py")):
        if path.stem.startswith("_"):
            continue
        try:
            script = _read(path)
        except (OSError, SyntaxError):
            continue
        if script is None:
            continue
        scripts.append(script)
    return scripts


def discover(folder: Path | None = None) -> list[Script]:
    """The scripts the window may show, alphabetically.

    `GUI = False` is ABSOLUTE, and filtered here, once. It is the AUTHOR's
    switch, meaning this script is unfinished or belongs in a terminal, so a file
    saying it is listed nowhere in the app: not on the rail, and not in the
    Scripts dialog either.

    Whether the USER has hidden a tile is a different question with a different
    answer, kept in `prefs.py`. Keeping them apart is the point: they were once
    the same flag, so unticking a tile edited the script file, and the dialog had
    to re-list `False` scripts to let anyone undo it - which made the author's
    switch mean nothing.
    """
    return [script for script in discover_all(folder) if script.shown]


def _read(path: Path) -> Script | None:
    """Parse one file, or None if it is not a runnable configured script."""
    source = path.read_text(encoding="utf-8")
    lines = source.splitlines()

    start = end = None
    for i, line in enumerate(lines):
        if start is None:
            if _CONFIG_START.match(line.strip()):
                start = i
        elif _CONFIG_END.match(line.strip()):
            end = i
            break
    if start is None or end is None:
        return None

    tree = ast.parse(source)
    if not any(
        isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name == "main"
        for node in tree.body
    ):
        return None

    comments = _trailing_comments(source)
    fields: list[Field] = []
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name) or not target.id.isupper():
            continue
        # 1-based line numbers against 0-based marker indices: the block spans
        # the lines strictly between the two marker lines.
        if not (start + 1 < node.lineno <= end):
            continue
        literal = ast.get_source_segment(source, node.value)
        if literal is None:  # pragma: no cover - only if ast loses positions
            continue
        value = node.value
        fields.append(
            Field(
                name=target.id,
                literal=literal,
                comment=comments.get(value.end_lineno or node.lineno, ""),
                kind=_kind(path.stem, target.id, literal),
                lineno=value.lineno,
                col_offset=value.col_offset,
                end_lineno=value.end_lineno or value.lineno,
                end_col_offset=value.end_col_offset or 0,
            )
        )
    if not fields:
        return None

    doc = ast.get_docstring(tree) or ""
    first = doc.splitlines()[0] if doc else ""
    # Every script's docstring opens "filename.py - what it does." Take the
    # half after the dash as the subtitle; fall back to the whole line if a
    # future script does not follow the pattern.
    subtitle = first.split(" - ", 1)[1] if " - " in first else first
    return Script(
        path=path,
        title=path.stem.replace("_", " ").capitalize(),
        subtitle=_as_sentence(subtitle),
        # The whole docstring, minus the "filename.py - " opener, which the
        # title and subtitle already carry. Shown behind the info icon: what the
        # script does, what needs installing, where any weights land.
        doc=doc[len(first) :].strip() if doc.startswith(first) else doc,
        fields=tuple(fields),
        env_vars=_env_vars(tree),
        shown=_opted_in(source),
        source=source,
    )


def _opted_in(source: str) -> bool:
    """Whether the script says `GUI = True`, which is what puts it in the window.

    Opt-in, not opt-out: a script with no `GUI` line, or `GUI = False`, is not
    listed. A half-finished script, or one meant only for a terminal, therefore
    stays out of the window by simply not saying otherwise, and the line says in
    plain words what it does to anyone reading the file.

    Read from the whole module rather than from inside the CONFIG block, so the
    flag can sit above the block and never becomes an editable field in the form
    - it controls the app, not the script's behaviour.
    """
    for node in ast.parse(source).body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if isinstance(target, ast.Name) and target.id == "GUI":
            return isinstance(node.value, ast.Constant) and node.value.value is True
    return False


def _env_vars(tree: ast.Module) -> tuple[str, ...]:
    """Every environment variable the script reads, from its own source.

    Picks up `os.getenv("X")` and `os.environ.get("X")`, which is how all 18
    read their credentials. This is what lets the Keys dialog list exactly the
    credentials the scripts actually use, and lets a script's page say whether
    the ones it needs are available, without a hand-maintained list of key
    names anywhere.
    """
    names: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not node.args:
            continue
        func = node.func
        if not isinstance(func, ast.Attribute) or func.attr not in ("getenv", "get"):
            continue
        if func.attr == "get" and not (
            isinstance(func.value, ast.Attribute) and func.value.attr == "environ"
        ):
            continue
        first = node.args[0]
        if isinstance(first, ast.Constant) and isinstance(first.value, str):
            names.add(first.value)
    return tuple(sorted(names))


def _as_sentence(text: str) -> str:
    """A docstring fragment as a sentence: leading capital, closing full stop.

    The docstrings write the description as the tail of "filename.py - sorts a
    folder...", so it starts lower-case by design. Only the FIRST character is
    touched; the rest is left exactly as written, so "a LIVE Gmail account" and
    "(the capstone)" survive intact.
    """
    text = text.strip()
    if not text:
        return text
    text = text[0].upper() + text[1:]
    return text if text.endswith((".", "!", "?")) else f"{text}."


def _trailing_comments(source: str) -> dict[int, str]:
    """Map line number -> that line's trailing comment text, `#` stripped.

    Only comments with code before them on the same line count: a comment on
    its own line is a section note, not a description of a value. `tokenize`
    rather than a regex, so a `#` inside a string literal is not mistaken for
    the start of a comment.
    """
    found: dict[int, str] = {}
    lines = source.splitlines()
    try:
        tokens = tokenize.generate_tokens(io.StringIO(source).readline)
        for token in tokens:
            if token.type != tokenize.COMMENT:
                continue
            row, col = token.start
            if not lines[row - 1][:col].strip():
                continue  # a whole-line comment
            found[row] = token.string.lstrip("#").strip()
    except (tokenize.TokenError, IndentationError, IndexError):
        return found
    return found


def _kind(stem: str, name: str, literal: str) -> str:
    """Which widget the form should give this field.

    Returned kinds: `choice`, `bool`, `folder`, `open_file`, `save_file`,
    `long_text`, `text`. The path kinds only ever apply to STRING values,
    which is what keeps a list like `FILE_TYPES = []` from being handed a
    Browse button just because its name contains "FILE".
    """
    if (stem, name) in _CHOICES:
        return "choice"
    if literal in ("True", "False"):
        return "bool"

    is_string = literal.startswith(('"', "'", 'r"', "r'", 'R"', "R'"))
    if is_string:
        override = _PATH_KIND_OVERRIDES.get((stem, name))
        if override:
            return override
        if name.endswith(("_DIR", "_FOLDER")) or name in ("FOLDER", "DIRECTORY"):
            return "folder"
        if name.startswith(("OUTPUT_", "SAVE_")) or name.endswith("_TO"):
            return "save_file"
        if "FILE" in name or "PATH" in name or name in ("AUDIO", "SOURCE", "INPUT"):
            return "open_file"
        if len(literal) > 60 or name in _LONG_TEXT_NAMES:
            return "long_text"
        return "text"

    if literal.startswith(("[", "{")) and len(literal) > 40:
        return "long_text"
    return "text"


_LONG_TEXT_NAMES = frozenset(
    {"QUERY", "QUESTION", "INSTRUCTION", "SOURCE_TEXT", "PROMPT", "SYSTEM_PROMPT"}
)
"""String fields that get a multi-line box whatever their current length: the
default may be short but what you type in them is a paragraph."""


# The choices a few string fields accept. The scripts DO state these, in prose
# in their trailing comments ('"basic" | "advanced"', "tiny / base / small /
# medium / large"), but prose is not a list, and parsing English out of a
# comment would break the moment a comment was reworded. Keyed by (script,
# constant); the values are Python literals because that is what the field
# holds. A field not listed here stays a free-text box, which is the safe
# default - a wrong dropdown hides a valid value, a text box never does.
_CHOICES: dict[tuple[str, str], tuple[str, ...]] = {
    ("web_search", "SEARCH_DEPTH"): ('"basic"', '"advanced"'),
    ("web_search", "TOPIC"): ('"general"', '"news"'),
    ("web_search", "TIME_RANGE"): ("None", '"day"', '"week"', '"month"', '"year"'),
    ("audio_transcriber", "MODEL"): ('"tiny"', '"base"', '"small"', '"medium"', '"large"'),
    # Fewer sizes than its sister above, and deliberately: `base` sits between
    # tiny and small with no niche, and `medium` is the same 1.5 GB as `turbo`
    # while being slower and less accurate.
}


# Path fields whose NAME points the wrong way. The name rules in `_kind` are
# right for the great majority, and these are the exceptions, each with the
# reason:
#   random_picker.SOURCE   accepts a folder OR a .txt file; the folder is the
#                          main use and its default value is a folder path, so
#                          Browse offers a folder. A file path can still be
#                          typed or pasted.
#   random_picker.COPY_TO  ends in _TO, but it is the folder the picked files
#                          are copied INTO, not a file to write.
_PATH_KIND_OVERRIDES: dict[tuple[str, str], str] = {
    ("random_picker", "SOURCE"): "folder",
    ("random_picker", "COPY_TO"): "folder",
}


def choices_for(stem: str, name: str) -> tuple[str, ...]:
    """The literal options for a `choice` field."""
    return _CHOICES.get((stem, name), ())
