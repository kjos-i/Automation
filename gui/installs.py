"""What a script needs installed, and installing it.

The list of requirements comes from the script's own `import` statements, not
from its `Setup:` docstring line. Prose can drift from behaviour; imports cannot.
Walking the AST also recovers two things the prose does not say, because the
scripts already encode them:

  - **optional**: an import wrapped in `try / except ImportError` whose handler
    does NOT call `sys.exit` is one the script carries on without, e.g.
    `doc_finder` skipping PDFs when `pypdf` is absent.
  - **conditional**: an import inside `if SOME_CONFIG:` is only needed in that
    mode, e.g. `rename_files` needing `openai` only when `USE_LLM` is on.

Everything here runs pip through the interpreter that runs the SCRIPTS, not the
GUI's own. They are the same today; in a packaged build they will not be.
"""

from __future__ import annotations

import ast
import asyncio
import re
import sys
import tomllib
from collections.abc import Callable
from dataclasses import dataclass

from catalog import AUTOMATION_DIR, Script

# Import name -> pip name, for the ones where the two differ in a way no rule
# can guess. Underscore-to-hyphen is handled by `_pip_name` and covers
# `faster_whisper` and `langchain_openai`, so only the genuinely irregular ones
# are listed here.
_PIP_NAMES = {
    "dotenv": "python-dotenv",
    "tavily": "tavily-python",
    "google": "google-genai",
    "docx": "python-docx",
    "win32com": "pywin32",
}


@dataclass(frozen=True)
class Requirement:
    """One third-party module a script imports."""

    module: str
    """The import name, which is what `find_spec` tests."""

    package: str
    """The pip name, which is what an install command needs."""

    optional: bool
    """True when the script handles the import failing and carries on."""

    condition: str
    """The CONFIG constant this import is gated on, or "" if it is
    unconditional."""

    def describe(self) -> str:
        if self.condition:
            return f"needed when {self.condition} is on"
        return "optional" if self.optional else "required"


def _pip_name(module: str) -> str:
    return _PIP_NAMES.get(module, module.replace("_", "-"))


def requirements(script: Script) -> tuple[Requirement, ...]:
    """Every third-party module `script` imports, with how it is needed."""
    found: dict[str, Requirement] = {}
    _walk(ast.parse(script.source), optional=False, condition="", out=found)
    return tuple(found[k] for k in sorted(found))


def _walk(node: ast.AST, *, optional: bool, condition: str, out: dict[str, Requirement]) -> None:
    """Recurse, carrying whether we are inside a handled `try` or a config-gated
    `if`, so each import is recorded with the context it sits in."""
    for child in ast.iter_child_nodes(node):
        if isinstance(child, ast.Try):
            handled = _handles_import_error(child)
            body_optional = optional or (handled and not _handler_exits(child))
            for sub in child.body:
                _walk(sub, optional=body_optional, condition=condition, out=out)
            _record(child.body, optional=body_optional, condition=condition, out=out)
            for sub in [*child.handlers, *child.orelse, *child.finalbody]:
                _walk(sub, optional=optional, condition=condition, out=out)
            continue

        if (
            isinstance(child, ast.If)
            and isinstance(child.test, ast.Name)
            and child.test.id.isupper()
        ):
            for sub in child.body:
                _walk(sub, optional=optional, condition=child.test.id, out=out)
            _record(child.body, optional=optional, condition=child.test.id, out=out)
            for sub in child.orelse:
                _walk(sub, optional=optional, condition=condition, out=out)
            continue

        _record([child], optional=optional, condition=condition, out=out)
        _walk(child, optional=optional, condition=condition, out=out)


def _record(
    nodes: list[ast.AST], *, optional: bool, condition: str, out: dict[str, Requirement]
) -> None:
    """Add any import statements directly in `nodes`. First sighting wins, so an
    unconditional import is not later downgraded by a conditional one."""
    for node in nodes:
        names: list[str] = []
        if isinstance(node, ast.Import):
            names = [alias.name.split(".")[0] for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names = [node.module.split(".")[0]]
        for name in names:
            if name in sys.stdlib_module_names or name in out:
                continue
            out[name] = Requirement(
                module=name, package=_pip_name(name), optional=optional, condition=condition
            )


def _handles_import_error(node: ast.Try) -> bool:
    for handler in node.handlers:
        if handler.type is None:
            return True
        names = (
            [handler.type] if not isinstance(handler.type, ast.Tuple) else list(handler.type.elts)
        )
        if any(isinstance(n, ast.Name) and n.id == "ImportError" for n in names):
            return True
    return False


def _handler_exits(node: ast.Try) -> bool:
    """Whether the `except ImportError` handler stops the script.

    `sys.exit(...)` or a bare `raise` means the dependency is required; a
    `print` and carrying on means it is optional. This is the distinction the
    scripts already draw, so nothing has to be declared twice.
    """
    for handler in node.handlers:
        for sub in ast.walk(handler):
            if isinstance(sub, ast.Raise):
                return True
            if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute | ast.Name):
                name = sub.func.attr if isinstance(sub.func, ast.Attribute) else sub.func.id
                if name == "exit":
                    return True
    return False


# ----- what the neighbouring projects depend on -----------------------------


def _normalise(name: str) -> str:
    """A package name in the form PEP 503 compares by: lower case, with runs of
    `-`, `_` and `.` collapsed to a single hyphen. So `python_dotenv` and
    `Python-Dotenv` are recognised as the same package."""
    return re.sub(r"[-_.]+", "-", name).lower()


def _requirement_name(spec: str) -> str:
    """The bare package name from a requirement string, dropping the version,
    the extras and any environment marker: `torch>=2.6,<3` becomes `torch`."""
    return _normalise(re.split(r"[<>=!~;\[\s]", spec.strip(), maxsplit=1)[0])


def declared_by_neighbours(packages: list[str]) -> dict[str, list[str]]:
    """Which projects beside Automation declare each of `packages`.

    The venv is shared with the other projects in the parent folder, so
    uninstalling a package for one Automation script can break one of them.
    This reads their `pyproject.toml` files and reports the overlap by name, so
    the confirm dialog can say "Epistemon needs this" rather than a vague
    warning about shared environments.

    Self-cancelling by design: once Automation is installed on its own with no
    sibling projects beside it, there is nothing to find and no warning appears.
    A project whose toml is missing or unreadable is skipped rather than raised
    on - this is advice, and must never stop the dialog from opening.
    """
    wanted = {_normalise(p): p for p in packages}
    if not wanted:
        return {}

    found: dict[str, list[str]] = {}
    for toml_path in sorted(AUTOMATION_DIR.parent.glob("*/pyproject.toml")):
        if toml_path.parent == AUTOMATION_DIR:
            continue
        try:
            data = tomllib.loads(toml_path.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError):
            continue

        project = data.get("project", {})
        specs: list[str] = list(project.get("dependencies", []))
        for group in project.get("optional-dependencies", {}).values():
            specs.extend(group)
        for group in data.get("dependency-groups", {}).values():
            specs.extend(s for s in group if isinstance(s, str))

        name = project.get("name") or toml_path.parent.name
        for spec in specs:
            key = _requirement_name(spec)
            if key in wanted:
                found.setdefault(wanted[key], [])
                if name not in found[wanted[key]]:
                    found[wanted[key]].append(name)
    return found


# ----- the interpreter that runs the scripts --------------------------------


def interpreter() -> str:
    """The Python that scripts (and therefore pip) run under.

    One place to change when the packaged build gives the GUI its own frozen
    runtime and a separate real Python for the scripts."""
    return sys.executable


async def installed(modules: tuple[str, ...]) -> dict[str, bool]:
    """Which of `modules` can be imported by the script interpreter.

    Uses `find_spec`, which answers without importing, so checking a heavy
    package costs nothing and cannot run its top-level code. Runs out of
    process, so the answer is about the interpreter that will run the script
    rather than the one drawing the window.
    """
    if not modules:
        return {}
    probe = (
        "import importlib.util as u, json, sys;"
        f"print(json.dumps({{m: u.find_spec(m) is not None for m in {list(modules)!r}}}))"
    )
    proc = await asyncio.create_subprocess_exec(
        interpreter(),
        "-c",
        probe,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    out, _ = await proc.communicate()
    try:
        import json

        return json.loads(out.decode("utf-8", errors="replace"))
    except (ValueError, UnicodeDecodeError):
        return dict.fromkeys(modules, False)


async def pip(args: list[str], on_line: Callable[[str], None]) -> int:
    """Run pip in the script interpreter, streaming its output a line at a time.

    NEVER pass `-U`: upgrading a package in an environment shared with other
    projects is how a working project breaks from a window that has nothing to
    do with it.
    """
    cmd = [interpreter(), "-m", "pip", *args]
    on_line(f"$ {' '.join(cmd)}")
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        limit=1024 * 1024,
    )
    assert proc.stdout is not None
    while True:
        raw = await proc.stdout.readline()
        if not raw:
            break
        on_line(raw.decode("utf-8", errors="replace").rstrip("\r\n"))
    return await proc.wait()
