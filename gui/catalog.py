"""Find the runnable scripts in `Automation/` and read their CONFIG blocks.

`set_shown` is the ONLY thing here that writes to a script, and it rewrites
exactly one line, `GUI = True` or `GUI = False`, which is the flag that decides
whether the script appears in the window. It refuses to write if the edit would
change anything else. Everything else the GUI shows comes from the file as it
already stands:

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


def discover(folder: Path | None = None, *, only_shown: bool = True) -> list[Script]:
    """Every runnable script in `folder`, alphabetically.

    `only_shown` (the default) returns just the ones saying `GUI = True`, which
    is what the rail lists. Pass False for the Add-scripts dialog, which has to
    offer the hidden ones too; each result carries `shown`.

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
        if only_shown and not script.shown:
            continue
        scripts.append(script)
    return scripts


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


def set_shown(path: Path, value: bool) -> None:
    """Write `GUI = True` or `GUI = False` into a script, and nothing else.

    This is the one place the app modifies a script, and it is deliberately
    narrow: it rewrites the value of an existing `GUI` line, or inserts the line
    just after the docstring if there is none. The CONFIG block, the code and
    the docstring are never touched.

    Before writing, the result is re-parsed and its module-level constants
    compared with the original. If anything other than `GUI` moved, appeared or
    vanished, the write is abandoned and `ValueError` is raised rather than
    saving a file the edit did not fully understand.
    """
    original = path.read_text(encoding="utf-8")
    literal = "True" if value else "False"
    tree = ast.parse(original)

    node = next(
        (
            n
            for n in tree.body
            if isinstance(n, ast.Assign)
            and len(n.targets) == 1
            and isinstance(n.targets[0], ast.Name)
            and n.targets[0].id == "GUI"
        ),
        None,
    )

    lines = original.splitlines(keepends=True)
    if node is not None:
        # Replace just the value, so any trailing comment on the line survives.
        # `ast` column offsets are UTF-8 byte offsets, hence the encode/decode.
        target = node.value
        raw = lines[target.lineno - 1].encode("utf-8")
        patched = raw[: target.col_offset] + literal.encode("utf-8") + raw[target.end_col_offset :]
        lines[target.lineno - 1] = patched.decode("utf-8")
    else:
        doc = tree.body[0] if tree.body else None
        if not (isinstance(doc, ast.Expr) and isinstance(doc.value, ast.Constant)):
            raise ValueError(f"{path.name} has no module docstring to insert after")
        at = doc.end_lineno or 0
        lines[at:at] = ["\n", f"GUI = {literal}  # show this script in the Automation GUI window\n"]

    updated = "".join(lines)
    if _constant_names(ast.parse(updated)) != _constant_names(tree) | {"GUI"}:
        raise ValueError(f"refused to write {path.name}: the edit changed more than GUI")
    path.write_text(updated, encoding="utf-8")


def _constant_names(tree: ast.Module) -> set[str]:
    """The module-level uppercase constant names, used as a before/after
    fingerprint so `set_shown` can prove it changed nothing else."""
    return {
        n.targets[0].id
        for n in tree.body
        if isinstance(n, ast.Assign)
        and len(n.targets) == 1
        and isinstance(n.targets[0], ast.Name)
        and n.targets[0].id.isupper()
    }


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
