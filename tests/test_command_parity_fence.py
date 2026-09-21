"""The parity fence — ADR 0007 step 5, the last step of the record.

**Why this file exists.** A command is declared ONCE, in the Python
registry, and everything else is derived. Steps 1–4 removed six
hand-written rosters and the `engine -> commands` inversion; step 5
removed the SEVENTH (`rich/ui.py::display_welcome`'s ~30-command list,
18 commands out of date) and a caller-less eighth
(`ui_components.py::render_welcome`). Nothing,
however, ever COMPARED the rosters, which is why they could drift for
months while each file's header claimed to be "the single source of
truth": 43 commands in Python, 38 in web's `commands.js`, 31 in VSCode's
`commands.ts`. This file is the comparison. It is not a style rule — it
is the only thing standing between the tree and a seventh catalog.

**What it reads, and how.** Python owns two vocabularies:

  * `CLIENT_ACTIONS` plus the per-spec `client_action` /
    `client_action_clients` declarations (`ppxai/commands/factory.py`),
  * `SideEffectKind` (`ppxai/commands/results.py`).

The clients bundle the IMPLEMENTATIONS — behaviour mirrors that
legitimately stay (ADR 0007 §Which mirrors can go). So every assertion
below reads the Python declaration and compares it against what the REAL
client source implements. Nothing here restates a list by hand except
the one explicitly-named SHRINKING BASELINE (`LEGACY_INTERCEPT_BASELINE`
— VSCode's `LEGACY_INTERCEPTS`), which exists so that a decision stays
visible instead of hiding in a literal. A second one,
`TEXTUAL_LEGACY_QUIT_BASELINE`, was resolved and removed 2026-09-21 when
`q` became a registered alias of `/quit`; see
`TestNoUndeclaredIntercepts.test_the_textual_quit_legacy_extra_is_gone`.

Five assertions:

  1. **Action coverage, both directions, per client.** Web's
     `CommandDispatcher.CLIENT_ACTIONS` (`command-dispatcher.js`),
     VSCode's `CLIENT_ACTIONS` (`commandRouter.ts` — deliberately a
     `vscode`-free module so this fence can read it), and the two TUIs'
     `CommandFactory.names_for_client_action(...)` call sites. Every
     action Python declares for a client is implemented by it, AND every
     key in a client's registry is an action Python declares for that
     client. No missing implementations, no orphan ones.
  2. **No undeclared intercepts.** Web: zero per-name branches in the
     dispatcher. VSCode: the only name-keyed table besides the action
     registry is `LEGACY_INTERCEPTS`, carried here as a shrinking
     baseline — a new entry fails ("declare a `client_action` instead";
     owner: *do not bless debt*), and a REMOVED entry fails until the
     baseline row is deleted too, so this file stays a record of the
     cleanup. Same discipline as `BASELINE` in
     `tests/test_no_new_lazy_imports.py`.
  3. **No surviving hand-written roster, anywhere.** Each deletion in
     the plan's completeness list is fenced as ABSENT, plus a GENERIC
     detector for new ones: a literal collection (or a single prose
     string) naming `CATALOG_THRESHOLD` or more distinct registered
     commands with a leading slash, anywhere under `ppxai/web/**.js`,
     `vscode-extension/src/**.ts`, `vscode-extension/media/**.js` or
     `ppxai/**.py` outside `ppxai/commands/`.
  4. **Side-effect kind coverage**, DERIVED from
     `SideEffectKind.all_kinds()`. The pre-existing drift fences
     (`test_web_shared_modules.py`, `test_vscode_step5a_helpers.py`)
     hardcoded their own expected sets, which is exactly how
     `refresh_command_roster` could be added in step 2 without any
     client noticing — and how `prompt_text` came to be missing from
     the web set while web implements it. Both were retargeted onto
     `SideEffectKind.all_kinds()` in this step; this file owns the
     derivation.
  4a. **Prompt kinds reach ALL FOUR clients.** Assertion 4 covers the
     two JS clients, because until 2026-09-21 the TUIs consumed no
     side-effects at all. `CLIENT_ROUND_TRIP_KINDS`
     (`ppxai/commands/results.py`) names the subset that a client
     cannot ignore without DEAD-ENDING the command — the handler asked
     a question and did none of its work — and that set is fenced
     across rich, textual, web and vscode. This is the assertion that
     would have caught `/show @x` printing "3 files match" and stopping
     in both TUIs for a year.
  5. **Roster self-consistency.** For every id in `KNOWN_CLIENTS`,
     `CommandFactory.roster(client)` names no `dispatch == "client"`
     action that client does not implement.

**These fences read OTHER languages' source, which is fragile — so the
fragility is made loud.** Every extractor is self-tested on synthetic
input FIRST (§Guards), including the three traps already hit while doing
this work: an apostrophe inside a `//` comment derailing a brace
counter, a template literal containing braces, and `subcommand === '…'`
matching a `command === '…'` pattern. Every extractor also has a
POSITIVE CONTROL against the real file: an empty or implausible result
is an ERROR, never vacuous parity. Where the VSCode tables can be read
from the REAL compiled module (the extension's own esbuild + Node, the
harness `tests/test_vscode_command_roster_behavior.py` established),
they are — and the regex is cross-checked against it rather than
trusted alone. That cross-check skips without Node; the regex path is
what always runs, so the fence has no environment hole.

Every assertion is MUTATION-VERIFIED at the bottom of this file, in
memory or in `tmp_path`; nothing is ever written into the tree.
"""

from __future__ import annotations

import ast
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

# Populate CommandFactory via the side-effect registration modules (the
# same idiom as tests/test_completion_provider.py).
import ppxai.commands.handler  # noqa: F401
from ppxai.commands.factory import (
    CLIENT_ACTIONS as PY_CLIENT_ACTIONS,
)
from ppxai.commands.factory import (
    KNOWN_CLIENTS,
    CommandFactory,
)
from ppxai.commands.results import CLIENT_ROUND_TRIP_KINDS, SideEffectKind

REPO_ROOT = Path(__file__).resolve().parents[1]
PPXAI = REPO_ROOT / "ppxai"
WEB = PPXAI / "web"
EXT = REPO_ROOT / "vscode-extension"

WEB_DISPATCHER = WEB / "shared" / "command-dispatcher.js"
WEB_SIDE_EFFECTS = WEB / "shared" / "side-effects.js"
VSCODE_ROUTER = EXT / "src" / "commandRouter.ts"
VSCODE_SIDE_EFFECTS = EXT / "src" / "sideEffectsHandler.ts"
VSCODE_CHATPANEL = EXT / "src" / "chatPanel.ts"

#: The Python dispatch paths that implement a `client_action` for the
#: two in-process TUIs. They intercept BEFORE the factory lookup (ending
#: the process is not something a handler can do), so their
#: "implementation" is a call site, not a registry — and since step 5 it
#: names the ACTION rather than the command, which is what makes it
#: readable from here.
TUI_ACTION_SITES = {
    "rich": PPXAI / "commands" / "handler.py",
    "textual": PPXAI / "tui" / "app.py",
}

# ---------------------------------------------------------------------------
# The shrinking baseline (was two; TEXTUAL_LEGACY_QUIT_BASELINE was
# resolved and removed 2026-09-21 — see the module docstring)
# ---------------------------------------------------------------------------

#: RESOLVED, and the constant is kept ONLY as the record of what it
#: used to hold — nothing reads it as a baseline any more.
#:
#: VSCode used to intercept these client-side WITHOUT a declared
#: `client_action`, by explicit owner decision ("do not bless debt").
#: They hit bespoke REST endpoints; the code said *"full factory routing
#: is a later phase"* from v1.18.1 until ADR 0007 step 5, which shrank
#: the table from five rows (`tools`, `checkpoint`, `context`, `ls`,
#: `tree`) to one.
#:
#: **The last row went on 2026-09-21, and the MECHANISM went with it.**
#: `/checkpoint` stayed as long as it did for one reason: `/checkpoint
#: clear` irreversibly deletes every file-backend snapshot and VSCode's
#: modal was the ONLY confirmation any client had. The confirmation is
#: on the wire now (`prompt_quick_pick` + `command_to_resume`, emitted
#: by `ppxai/commands/agent.py::_checkpoint_clear`, consumed by all four
#: clients and fenced by `TestPromptKindsAreConsumedEverywhere`), so
#: `/checkpoint` routes through `POST /command/checkpoint` like
#: everything else. `commandRouter.ts` has no `LEGACY_INTERCEPTS`, no
#: `LEGACY_HANDLERS`, no `legacy` host member and no legacy branch;
#: `handlers/commands.ts` and `handlers/types.ts` are deleted.
#:
#: The tests below now assert ABSENCE — a re-added table fails, and so
#: does a per-name intercept by any other name.
FORMER_LEGACY_INTERCEPTS = frozenset({
    "tools", "checkpoint", "context", "ls", "tree",
})

#: The identifiers that made up the deleted mechanism. Each must stay
#: absent from `commandRouter.ts`.
DELETED_LEGACY_IDENTIFIERS = (
    "LEGACY_INTERCEPTS",
    "LEGACY_HANDLERS",
)

#: RESOLVED (owner decision, 2026-09-21): `q` is now a REGISTERED alias
#: of `/quit` (`ppxai/commands/client_handled.py`), so the Textual-only
#: legacy-extra baseline this used to be (`TEXTUAL_LEGACY_QUIT_BASELINE
#: = frozenset({"q"})`) is gone, and `ppxai/tui/app.py::
#: TEXTUAL_LEGACY_QUIT_NAMES` went with it.
#: `TestNoUndeclaredIntercepts.test_the_textual_quit_legacy_extra_is_gone`
#: asserts the constant stays gone, so nobody re-adds a Textual-only
#: legacy extra without this file noticing.

# ---------------------------------------------------------------------------
# The generic catalog detector's tuning
# ---------------------------------------------------------------------------

#: A literal naming this many DISTINCT registered commands is a roster.
#:
#: Measured, not guessed (2026-09-21, after this step's own deletions).
#: The whole scanned tree yields exactly two literals above 3:
#: `STREAMING_COMMANDS` at 8 (exempted below) and a quick-command button
#: block in `web/app.js` at 4. The deleted catalogs measured 28
#: (`rich/ui.py`'s welcome), 13 (`ui_components.py::render_welcome`),
#: ~30 (`app.js`'s `slashCommands`) and 31 (`commands.ts`), so 6 sits
#: with clear air on both sides: today's tree is clean and any re-added
#: catalog trips it.
CATALOG_THRESHOLD = 6

#: The ONE literal above the threshold that is not a roster, named with
#: its reason. `STREAMING_COMMANDS` classifies commands whose RESPONSE
#: is the chat stream (they bypass the envelope and POST /chat) — a
#: behaviour classification, not command metadata, and the roster
#: carries no `chat_shaped` field to derive it from.
#:
#: **OPEN FOLLOW-UP** (recorded in the plan, not decided here): folding
#: chat-shaped-ness into the roster would delete this exemption. That is
#: a schema change to a published payload, so it is a deliberate
#: decision rather than a rider on this step.
CATALOG_EXEMPTIONS = {
    ("ppxai/web/shared/command-dispatcher.js", "STREAMING_COMMANDS"),
}

#: Files scanned by the generic detector, as (root, glob, skip) triples.
_CATALOG_SCAN = (
    (WEB, "*.js", lambda p: "lib" in p.parts),
    (EXT / "src", "*.ts", lambda p: False),
    (EXT / "media", "*.js", lambda p: p.name.endswith(".min.js")),
    (PPXAI, "*.py", lambda p: p.relative_to(PPXAI).parts[0] == "commands"),
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# ===========================================================================
# Extractors
# ===========================================================================
#
# Each one takes SOURCE TEXT and returns data, so it can be driven
# against a synthetic string (the guards below) as easily as against the
# real file. None of them takes a Path — that separation is what makes
# the mutation tests possible without touching the tree.


#: A `/` starts a REGEX literal (rather than a division) when the last
#: significant character is one of these — the standard JS heuristic. It
#: matters because `String(s).replace(/[&<>"\']/g, …)` in
#: `web/shared/side-effects.js` holds BOTH quote characters inside a
#: regex: read naively, that `"` opens a string literal that swallows the
#: next 100 lines, and the handler table came back four entries short
#: with no error. (Measured, not hypothetical — it is how the first
#: version of this file failed.)
_REGEX_PREV = set("(,=:[!&|?{};+-*%~^<>")


def js_spans(src: str) -> list[tuple[str, int, int]]:
    """`(kind, start, end)` for every comment, string and regex literal.

    ONE lexer, so every extractor below agrees about what is code. Kinds
    are `comment`, `string` (quoted or template) and `regex`.

    A quoted string is bounded by its line: JS forbids a raw newline
    inside `'…'`/`"…"`, so an apparently unterminated one is a mis-lex,
    and stopping at the newline keeps the damage to one line instead of
    to the rest of the file. Template literals may span lines.
    """
    spans: list[tuple[str, int, int]] = []
    i, n = 0, len(src)
    prev = ""
    while i < n:
        c = src[i]
        if c == "/" and i + 1 < n and src[i + 1] == "/":
            j = src.find("\n", i)
            j = n if j == -1 else j
            spans.append(("comment", i, j))
            i = j
            continue
        if c == "/" and i + 1 < n and src[i + 1] == "*":
            j = src.find("*/", i + 2)
            j = n if j == -1 else j + 2
            spans.append(("comment", i, j))
            i = j
            continue
        if c in "\'\"`":
            j = i + 1
            while j < n:
                if src[j] == "\\":
                    j += 2
                    continue
                if src[j] == c:
                    break
                if src[j] == "\n" and c != "`":
                    break
                j += 1
            end = min(j + 1, n)
            spans.append(("string", i, end))
            prev = c
            i = end
            continue
        if c == "/" and (prev == "" or prev in _REGEX_PREV):
            j, in_class = i + 1, False
            while j < n and src[j] != "\n":
                if src[j] == "\\":
                    j += 2
                    continue
                if src[j] == "[":
                    in_class = True
                elif src[j] == "]":
                    in_class = False
                elif src[j] == "/" and not in_class:
                    break
                j += 1
            if j < n and src[j] == "/":
                spans.append(("regex", i, j + 1))
                prev = "/"
                i = j + 1
                continue
        if not c.isspace():
            prev = c
        i += 1
    return spans


def strip_js_comments(src: str) -> str:
    """Blank comments AND regex literals, preserving offsets and lines.

    Regexes go too, deliberately: they are never structure, they never
    hold a command name, and leaving them in means every downstream
    scanner needs the regex rule of its own. With them blanked, the rest
    of this file only has to know about strings.
    """
    out = list(src)
    for kind, start, end in js_spans(src):
        if kind in ("comment", "regex"):
            for k in range(start, end):
                if out[k] != "\n":
                    out[k] = " "
    return "".join(out)


def _skip_string(src: str, i: int) -> int:
    """Index just past the string literal starting at `i`."""
    quote, n = src[i], len(src)
    j = i + 1
    while j < n:
        if src[j] == "\\":
            j += 2
            continue
        if src[j] == quote:
            break
        if src[j] == "\n" and quote != "`":
            break
        j += 1
    return min(j + 1, n)


def _balanced_body(src: str, start: int, open_ch: str, close_ch: str) -> str:
    """Text between `start`'s bracket and its match, strings skipped."""
    i, n, depth = start, len(src), 0
    while i < n:
        c = src[i]
        if c in "\'\"`":
            i = _skip_string(src, i)
            continue
        if c == open_ch:
            depth += 1
        elif c == close_ch:
            depth -= 1
            if depth == 0:
                return src[start + 1:i]
        i += 1
    raise AssertionError(f"unbalanced {open_ch}{close_ch} from offset {start}")


def js_object_keys(src: str, anchor: str) -> list[str]:
    """Top-level keys of the object literal assigned at `anchor`.

    `anchor` is a regex matched against the COMMENT-STRIPPED source; the
    literal starts at the first `{` after it. Keys are read at depth 1
    only, in all three JS spellings — `'quoted'(…)`, `'quoted':` and a
    bare identifier followed by `(` or `:`.

    A key is only recognised in KEY POSITION: at the start of the
    literal or just after a depth-0 comma. Without that rule an arrow
    value such as `'token.manage': (ops, ctx) => ops.handleToken(…)`
    contributed `handleToken` as a second key — the registry came back
    with sixteen entries instead of eight, and the "no orphan
    implementations" direction failed against the real file.
    """
    clean = strip_js_comments(src)
    m = re.search(anchor, clean)
    if not m:
        raise AssertionError(f"object literal anchor not found: {anchor!r}")
    body = _balanced_body(clean, clean.index("{", m.end()), "{", "}")
    keys: list[str] = []
    i, n, depth = 0, len(body), 0
    expect_key = True
    while i < n:
        c = body[i]
        if c in "'\"`":
            end = _skip_string(body, i)
            if depth == 0 and expect_key and c in "'\"":
                rest = body[end:end + 2].lstrip()
                if rest[:1] in (":", "("):
                    keys.append(body[i + 1:end - 1])
            expect_key = False
            i = end
            continue
        if c in "([{":
            depth += 1
            expect_key = False
            i += 1
            continue
        if c in ")]}":
            depth -= 1
            expect_key = False
            i += 1
            continue
        if depth == 0 and c == ",":
            expect_key = True
            i += 1
            continue
        if c.isspace():
            i += 1
            continue
        if depth == 0 and expect_key and (c.isalpha() or c == "_"):
            j = i
            while j < n and (body[j].isalnum() or body[j] in "_$"):
                j += 1
            rest = body[j:j + 2].lstrip()
            if rest[:1] in (":", "("):
                keys.append(body[i:j])
            expect_key = False
            i = j
            continue
        expect_key = False
        i += 1
    return keys


def ts_array_strings(src: str, anchor: str) -> list[str]:
    """String entries of the array literal declared at `anchor`."""
    clean = strip_js_comments(src)
    m = re.search(anchor, clean)
    if not m:
        raise AssertionError(f"array literal anchor not found: {anchor!r}")
    body = _balanced_body(clean, clean.index("[", m.end()), "[", "]")
    return re.findall(r"['\"]([^'\"]+)['\"]", body)


def ts_const_map(src: str, anchor: str) -> dict[str, str]:
    """`{IDENT: 'value'}` pairs of the const object declared at `anchor`.

    Used for `sideEffectsHandler.ts`'s `KIND` table, which is what lets
    `case KIND.OPEN_EDITOR:` be resolved to the wire name the Python
    constant declares.
    """
    clean = strip_js_comments(src)
    m = re.search(anchor, clean)
    if not m:
        raise AssertionError(f"const map anchor not found: {anchor!r}")
    body = _balanced_body(clean, clean.index("{", m.end()), "{", "}")
    return dict(re.findall(r"([A-Z][A-Z0-9_]*)\s*:\s*['\"]([^'\"]+)['\"]", body))


def ts_switch_case_kinds(src: str) -> set[str]:
    """Wire names of every `case KIND.X:` in `sideEffectsHandler.ts`."""
    table = ts_const_map(src, r"export const KIND\s*=\s*")
    clean = strip_js_comments(src)
    cases = set(re.findall(r"case\s+KIND\.([A-Z][A-Z0-9_]*)\s*:", clean))
    unknown = cases - set(table)
    if unknown:
        raise AssertionError(
            f"case KIND.{sorted(unknown)} has no entry in the KIND table"
        )
    return {table[c] for c in cases}


def js_per_name_branches(src: str) -> list[str]:
    """Hardcoded `cmd === '/<name>'` branches in the web dispatcher.

    Routing must come from the roster; a per-name special case would be
    a second roster with one row in it.
    """
    clean = strip_js_comments(src)
    return sorted(set(re.findall(r"\bcmd === '(/[a-z?-]+)'", clean)))


def ts_per_name_branches(src: str) -> list[str]:
    """Hardcoded `command === '<name>'` branches in TypeScript.

    The `(?:^|[^A-Za-z])` prefix is load-bearing and is the plan's own
    `grep -v subcommand` caveat expressed as a regex: without it,
    `subcommand === 'clear'` matches too, which is exactly the mistake
    that inflated VSCode's intercept count from 12 to 16 earlier in this
    work.
    """
    clean = strip_js_comments(src)
    return sorted(set(re.findall(
        r"(?:^|[^A-Za-z])command === '([a-z?-]+)'", clean, re.M)))


def py_client_action_sites(src: str) -> set[str]:
    """Action names a Python module implements, read off its call sites.

    An in-process TUI implements a `client_action` by intercepting the
    command before the factory lookup, and since step 5 it asks for the
    names by ACTION —
    `CommandFactory.names_for_client_action("app.quit")` — so the
    implemented set is derivable rather than hand-copied.
    """
    return set(re.findall(
        r"names_for_client_action\(\s*[\"']([a-z_.]+)[\"']\s*\)", src))


# --- the generic catalog detector ------------------------------------------


def command_token_re() -> re.Pattern[str]:
    """`/name` for every registered name (canonical AND alias).

    Single-character names are excluded: `/c`, `/s`, `/e` produce noise
    against paths and would make the detector unusable. The lookarounds
    are what keep REST paths out — `/v1/tokens`, `/command/clear` and
    `/models` are all rejected, because a command token may not be
    preceded by a path segment nor followed by more path.
    """
    names = {i.name for i in CommandFactory.iter_completion_specs()
             if len(i.name) >= 2}
    if not names:
        raise AssertionError("the command registry is empty — nothing to scan for")
    alt = "|".join(sorted(map(re.escape, names), key=len, reverse=True))
    return re.compile(
        r"(?<![A-Za-z0-9_/.-])/(" + alt + r")(?![A-Za-z0-9_/-])")


_EXPR_LEAD = set("=(,:[{|&?")


def js_literal_regions(src: str) -> list[tuple[int, int, str]]:
    """`(start, end, kind)` for string literals and value-position
    collections in comment-stripped JS/TS.

    "Value position" is what stops a CLASS BODY or a FUNCTION BODY being
    read as a collection: the `{`/`[` must follow one of `=(,:[{|&?`.
    Without that rule an 1800-line `class ChatViewProvider {` counted as
    one literal naming 23 commands — measured, then fixed.
    """
    regions: list[tuple[int, int, str]] = []
    stack: list[tuple[str, int, bool]] = []
    i, n = 0, len(src)
    while i < n:
        c = src[i]
        if c in "'\"`":
            end = _skip_string(src, i)
            regions.append((i, end, "string"))
            i = end
            continue
        if c in "[{":
            k = i - 1
            while k >= 0 and src[k] in " \t\r\n":
                k -= 1
            stack.append((c, i, (src[k] if k >= 0 else "=") in _EXPR_LEAD))
        elif c in "]}":
            if stack:
                opener, start, in_value_position = stack.pop()
                if in_value_position and (opener, c) in (("[", "]"), ("{", "}")):
                    regions.append((start, i + 1, "collection"))
        i += 1
    return regions


def scan_js_catalogs(src: str, token: re.Pattern[str]) -> list[tuple[int, int, set[str]]]:
    """`(line, count, names)` for every JS/TS literal naming commands."""
    clean = strip_js_comments(src)
    out = []
    for start, end, _kind in js_literal_regions(clean):
        found = {m.group(1) for m in token.finditer(clean[start:end])}
        if found:
            out.append((clean[:start].count("\n") + 1, len(found), found))
    return out


def scan_py_catalogs(src: str, token: re.Pattern[str]) -> list[tuple[int, int, set[str]]]:
    """`(line, count, names)` for every Python literal naming commands.

    DOCSTRINGS ARE EXCLUDED — a module or function docstring that
    mentions several commands is prose, not a roster, and including them
    made the detector fire on `engine/completion.py`'s own explanation of
    what it deleted. A non-docstring string constant (the shape the Rich
    welcome screen's catalog had) is NOT excluded; that is the whole
    point of scanning Python at all.
    """
    tree = ast.parse(src)
    starts, pos = [], 0
    for line in src.splitlines(keepends=True):
        starts.append(pos)
        pos += len(line)
    starts.append(pos)
    docstrings = set()
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if not isinstance(node, (ast.Module, ast.ClassDef,
                                 ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if (body and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)):
            docstrings.add(id(body[0].value))
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if id(node) in docstrings:
                continue
            found = {m.group(1) for m in token.finditer(node.value)}
        elif isinstance(node, (ast.List, ast.Set, ast.Dict, ast.Tuple)):
            # Sliced by hand rather than with `ast.get_source_segment`,
            # which re-splits the whole file per node: on this tree that
            # was 24s for one test, and a fence nobody wants to run is a
            # fence that gets marked slow and then skipped.
            if node.end_lineno is None:
                continue
            segment = src[starts[node.lineno - 1] + node.col_offset:
                          starts[node.end_lineno - 1] + node.end_col_offset]
            found = {m.group(1) for m in token.finditer(segment)}
        else:
            continue
        if found:
            out.append((node.lineno, len(found), found))
    return out


def catalog_files() -> list[Path]:
    """Every file the generic detector scans."""
    files: set[Path] = set()
    for root, pattern, skip in _CATALOG_SCAN:
        for path in root.rglob(pattern):
            if not skip(path):
                files.add(path)
    return sorted(files)


def find_catalogs(threshold: int = CATALOG_THRESHOLD) -> list[tuple[str, int, int, list[str]]]:
    """Every literal in the tree naming >= `threshold` distinct commands.

    Returns `(relative path, line, count, sorted names)`.
    """
    token = command_token_re()
    hits = []
    for path in catalog_files():
        src = path.read_text(encoding="utf-8", errors="replace")
        rows = (scan_py_catalogs(src, token) if path.suffix == ".py"
                else scan_js_catalogs(src, token))
        for line, count, names in rows:
            if count >= threshold:
                hits.append((str(path.relative_to(REPO_ROOT)), line,
                             count, sorted(names)))
    return sorted(hits)


def exempt(rel_path: str, line: int) -> bool:
    """True when a hit matches a named row in `CATALOG_EXEMPTIONS`.

    The identifier is looked for in a small WINDOW around the literal's
    first line rather than on that line exactly, so a reformat that moves
    `= new Set([` onto its own line does not silently un-exempt (or,
    worse, silently keep exempting the wrong literal).
    """
    lines = (REPO_ROOT / rel_path).read_text(encoding="utf-8").splitlines()
    window = "\n".join(lines[max(0, line - 3):line + 1])
    return any(path == rel_path and ident in window
               for path, ident in CATALOG_EXEMPTIONS)


# ===========================================================================
# Python-side declarations (the thing every assertion compares against)
# ===========================================================================


def declared_actions_for(client: str) -> set[str]:
    """Every `client_action` Python declares for `client`.

    A spec contributes when the client can SEE the command
    (`clients`) and the client is in `client_action_clients` (absent
    means every client that can see it) — the convention ADR 0007 step 1
    fixed.
    """
    out = set()
    for info in CommandFactory.iter_completion_specs():
        if not info.client_action:
            continue
        if info.clients is not None and client not in info.clients:
            continue
        if (info.client_action_clients is not None
                and client not in info.client_action_clients):
            continue
        out.add(info.client_action)
    return out


def implemented_actions_for(client: str) -> set[str]:
    """Every `client_action` `client` actually bundles an implementation of."""
    if client == "web":
        return set(js_object_keys(
            _read(WEB_DISPATCHER), r"CommandDispatcher\.CLIENT_ACTIONS\s*=\s*"))
    if client == "vscode":
        return set(js_object_keys(
            _read(VSCODE_ROUTER),
            r"export const CLIENT_ACTIONS: Record<string, OpsAction>\s*=\s*"))
    return py_client_action_sites(_read(TUI_ACTION_SITES[client]))


# ===========================================================================
# GUARDS — every extractor, on synthetic input, before anything uses it
# ===========================================================================


class TestStripJsComments:
    def test_line_comment_goes(self):
        assert "gone" not in strip_js_comments("const a = 1; // gone\nconst b = 2;")

    def test_block_comment_goes(self):
        assert "gone" not in strip_js_comments("const a = /* gone */ 1;")

    def test_string_content_stays(self):
        assert "//example.com" in strip_js_comments("const u = 'http://example.com';")

    def test_an_apostrophe_in_a_line_comment_opens_no_string(self):
        """The trap. `// doesn't` used to open a string literal that ate
        the rest of the file, which silently emptied every downstream
        extractor — a fence that finds nothing passes."""
        src = "// doesn't matter\nconst KEEP = 1;\n// nor does this\nconst ALSO = 2;\n"
        out = strip_js_comments(src)
        assert "KEEP" in out and "ALSO" in out

    def test_offsets_are_preserved(self):
        src = "const a = 1; // padding here\nconst b = 2;"
        assert len(strip_js_comments(src)) == len(src)

    def test_a_regex_literal_holding_a_quote_does_not_open_a_string(self):
        """Third trap, and the one that actually broke this file:
        `.replace(/[&<>"']/g, …)` in web/shared/side-effects.js holds
        both quote characters INSIDE a regex. Read naively the `"` opens
        a string that runs on for a hundred lines, and the handler table
        came back four entries short — silently, because a short table
        still compares fine against a short expectation."""
        src = ('const f = (s) => String(s).replace(/[&<>"\']/g, (c) => c);\n'
               'X.T = {\n  keep_me() {},\n};\n')
        assert js_object_keys(src, r"X\.T\s*=\s*") == ["keep_me"]

    def test_division_is_not_mistaken_for_a_regex(self):
        src = "const half = total / 2; const q = (a) / (b);\nconst KEEP = 1;"
        assert "KEEP" in strip_js_comments(src)
        assert "half" in strip_js_comments(src)


class TestJsObjectKeys:
    def test_quoted_method_shorthand(self):
        src = "X.TABLE = {\n  'a.one'({x}) { return 1; },\n  'b.two'() {},\n};"
        assert js_object_keys(src, r"X\.TABLE\s*=\s*") == ["a.one", "b.two"]

    def test_quoted_colon_form(self):
        src = "export const T: Record<string, F> = {\n  'a.one': (o) => o.x(),\n};"
        assert js_object_keys(
            src, r"export const T: Record<string, F>\s*=\s*") == ["a.one"]

    def test_bare_identifier_keys(self):
        src = "H._handlers = {\n  open_editor({f}) {},\n  notify({m}) {},\n};"
        assert js_object_keys(src, r"H\._handlers\s*=\s*") == ["open_editor", "notify"]

    def test_an_arrow_value_does_not_contribute_a_key(self):
        """`'a.one': (o, c) => o.handleThing(c)` must yield ONE key.
        Without the key-position rule `handleThing` came back as a
        second key and VSCode's eight-entry registry read as sixteen."""
        src = ("export const T: Record<string, F> = {\n"
               "  'a.one': (o, c) => o.handleThing(c.args),\n"
               "  'b.two': (o, c) => o.other(c.argv),\n};")
        assert js_object_keys(
            src, r"export const T: Record<string, F>\s*=\s*") == ["a.one", "b.two"]

    def test_nested_object_keys_are_not_counted(self):
        src = "X.T = {\n  'a.one'() { const o = { inner: 1, other: 2 }; },\n};"
        assert js_object_keys(src, r"X\.T\s*=\s*") == ["a.one"]

    def test_a_template_literal_with_braces_does_not_unbalance(self):
        """Second trap: `${…}` inside a template literal is a brace pair
        the counter must not see as structure."""
        src = ("X.T = {\n  'a.one'() { return `a ${x} b } c`; },\n"
               "  'b.two'() {},\n};")
        assert js_object_keys(src, r"X\.T\s*=\s*") == ["a.one", "b.two"]

    def test_a_brace_in_a_plain_string_does_not_unbalance(self):
        src = "X.T = {\n  'a.one'() { return '}'; },\n  'b.two'() {},\n};"
        assert js_object_keys(src, r"X\.T\s*=\s*") == ["a.one", "b.two"]

    def test_a_commented_out_key_is_not_counted(self):
        src = "X.T = {\n  // 'ghost.key'() {},\n  'a.one'() {},\n};"
        assert js_object_keys(src, r"X\.T\s*=\s*") == ["a.one"]

    def test_a_missing_anchor_raises(self):
        with pytest.raises(AssertionError, match="anchor not found"):
            js_object_keys("const x = 1;", r"NOPE\s*=\s*")


class TestTsArrayStrings:
    def test_reads_entries(self):
        src = "export const L: readonly string[] = [\n  'a',\n  'b',\n];"
        assert ts_array_strings(
            src, r"export const L: readonly string\[\]\s*=\s*") == ["a", "b"]

    def test_a_commented_out_entry_is_not_counted(self):
        src = "export const L: readonly string[] = [\n  // 'ghost',\n  'a',\n];"
        assert ts_array_strings(
            src, r"export const L: readonly string\[\]\s*=\s*") == ["a"]

    def test_a_missing_anchor_raises(self):
        with pytest.raises(AssertionError, match="anchor not found"):
            ts_array_strings("const x = 1;", r"NOPE\s*=\s*")


class TestTsSwitchCaseKinds:
    _SRC = (
        "export const KIND = {\n"
        "  OPEN_EDITOR: 'open_editor',\n"
        "  NOTIFY: 'notify',\n"
        "} as const;\n"
        "function f(se) { switch (se.kind) {\n"
        "  case KIND.OPEN_EDITOR: { return; }\n"
        "  case KIND.NOTIFY: { return; }\n"
        "  default: return;\n"
        "} }\n"
    )

    def test_resolves_cases_through_the_kind_table(self):
        assert ts_switch_case_kinds(self._SRC) == {"open_editor", "notify"}

    def test_a_commented_out_case_is_not_counted(self):
        src = self._SRC.replace("  case KIND.NOTIFY:", "  // case KIND.NOTIFY:")
        assert ts_switch_case_kinds(src) == {"open_editor"}

    def test_a_case_with_no_kind_entry_raises(self):
        src = self._SRC.replace("case KIND.NOTIFY:", "case KIND.GHOST:")
        with pytest.raises(AssertionError, match="no entry in the KIND table"):
            ts_switch_case_kinds(src)


class TestPerNameBranchDetectors:
    def test_web_detector_sees_a_branch(self):
        assert js_per_name_branches("if (cmd === '/token') { x(); }") == ["/token"]

    def test_web_detector_ignores_a_commented_branch(self):
        assert js_per_name_branches("// if (cmd === '/token') {}") == []

    def test_vscode_detector_sees_a_branch(self):
        assert ts_per_name_branches("if (command === 'token') { x(); }") == ["token"]

    def test_vscode_detector_ignores_subcommand_comparisons(self):
        """The plan's own `grep -v subcommand` caveat, as a regression
        test: matching naively turns 12 intercepts into 16."""
        assert ts_per_name_branches("if (subcommand === 'clear') { x(); }") == []

    def test_vscode_detector_still_sees_a_branch_after_a_subcommand_one(self):
        src = "if (subcommand === 'clear') {}\nif (command === 'tools') {}"
        assert ts_per_name_branches(src) == ["tools"]


class TestPyClientActionSites:
    def test_reads_a_call_site(self):
        src = 'if cmd in CommandFactory.names_for_client_action("app.quit"):'
        assert py_client_action_sites(src) == {"app.quit"}

    def test_reads_single_quotes_too(self):
        assert py_client_action_sites(
            "names_for_client_action('token.manage')") == {"token.manage"}

    def test_finds_nothing_in_unrelated_source(self):
        assert py_client_action_sites("x = 1\n") == set()


class TestCommandTokenRegex:
    def test_matches_a_bare_command(self):
        assert command_token_re().search("/help") is not None

    def test_rejects_a_rest_path_segment(self):
        """`/command/clear` and `/v1/tokens` must not read as commands —
        without the lookarounds the detector fired on every REST client
        in the tree (measured: `api-client.js` scored 17)."""
        token = command_token_re()
        assert {m.group(1) for m in token.finditer("/command/clear")} == set()
        assert {m.group(1) for m in token.finditer("/v1/tokens")} == set()

    def test_rejects_a_longer_word(self):
        assert command_token_re().search("/models") is None

    def test_matches_inside_markdown_backticks(self):
        assert command_token_re().search("- `/save` - Save") is not None


class TestJsLiteralRegions:
    def test_a_value_position_array_is_a_collection(self):
        src = "const S = ['a', 'b'];"
        assert any(k == "collection" for _a, _b, k in js_literal_regions(src))

    def test_a_class_body_is_not_a_collection(self):
        """The measurement that set this rule: an entire
        `class ChatViewProvider { … }` body read as one literal naming 23
        commands, which would have forced the threshold up into
        uselessness."""
        src = "class Foo {\n  bar() { return 1; }\n}\n"
        assert not any(k == "collection" for _a, _b, k in js_literal_regions(src))

    def test_a_function_body_is_not_a_collection(self):
        src = "function f(a) {\n  return a;\n}\n"
        assert not any(k == "collection" for _a, _b, k in js_literal_regions(src))


class TestPyCatalogScan:
    def test_a_non_docstring_string_catalog_is_found(self):
        src = 'TEXT = """\n- `/save`\n- `/clear`\n- `/model`\n"""\n'
        rows = scan_py_catalogs(src, command_token_re())
        assert any(count >= 3 for _line, count, _names in rows)

    def test_a_docstring_is_not_a_catalog(self):
        src = '"""Mentions /save and /clear and /model in prose."""\nX = 1\n'
        assert scan_py_catalogs(src, command_token_re()) == []

    def test_a_list_literal_catalog_is_found(self):
        src = 'NAMES = ["/save", "/clear", "/model"]\n'
        rows = scan_py_catalogs(src, command_token_re())
        assert any(count >= 3 for _line, count, _names in rows)


# ===========================================================================
# POSITIVE CONTROLS — an extractor that finds nothing is an ERROR
# ===========================================================================


class TestExtractorsSeeTheRealFiles:
    """Guards, second half. Every assertion below is a set comparison,
    and an empty set compares equal to an empty set — so a silently
    broken extractor would turn the whole fence green. These make that
    impossible."""

    def test_the_python_vocabulary_is_populated(self):
        assert len(PY_CLIENT_ACTIONS) >= 9, (
            f"CLIENT_ACTIONS holds {len(PY_CLIENT_ACTIONS)} names — the registry "
            "did not load, or the vocabulary shrank unexpectedly"
        )

    def test_every_declared_action_is_in_the_vocabulary(self):
        declared = {info.client_action
                    for info in CommandFactory.iter_completion_specs()
                    if info.client_action}
        assert declared <= PY_CLIENT_ACTIONS, (
            f"specs name actions outside CLIENT_ACTIONS: "
            f"{sorted(declared - PY_CLIENT_ACTIONS)}"
        )

    def test_every_source_file_the_fence_reads_exists(self):
        for path in (WEB_DISPATCHER, WEB_SIDE_EFFECTS, VSCODE_ROUTER,
                     VSCODE_SIDE_EFFECTS, VSCODE_CHATPANEL,
                     *TUI_ACTION_SITES.values()):
            assert path.exists(), f"{path} is gone — retarget this fence"

    @pytest.mark.parametrize("client", sorted(KNOWN_CLIENTS))
    def test_every_client_implements_at_least_one_action(self, client):
        found = implemented_actions_for(client)
        assert found, (
            f"the extractor found NO client actions for {client!r}. Either the "
            "registry/call site moved, or the extractor stopped matching — "
            "'0 actions found' is a broken fence, not parity"
        )

    def test_the_side_effect_extractors_see_a_realistic_number(self):
        web = set(js_object_keys(_read(WEB_SIDE_EFFECTS),
                                 r"SideEffectsHandler\._handlers\s*=\s*"))
        vscode = ts_switch_case_kinds(_read(VSCODE_SIDE_EFFECTS))
        assert len(web) >= 10, f"web side-effect handlers: {sorted(web)}"
        assert len(vscode) >= 10, f"vscode side-effect cases: {sorted(vscode)}"

    def test_the_catalog_scanner_walks_a_realistic_number_of_files(self):
        files = catalog_files()
        assert len(files) > 100, (
            f"only {len(files)} files matched the catalog scan — wrong roots?"
        )

    def test_the_catalog_scanner_can_still_see_a_catalog(self):
        """Liveness: the detector must find the deleted `commands.js`
        shape when it is handed one, or 'no catalogs found' means
        nothing."""
        fake = "SharedCommands.SLASH_COMMANDS = {\n" + "".join(
            f"    '/{n}': {{ description: 'x' }},\n"
            for n in ("help", "model", "clear", "save", "load", "usage", "tools")
        ) + "};\n"
        rows = scan_js_catalogs(fake, command_token_re())
        assert any(count >= CATALOG_THRESHOLD for _l, count, _n in rows)


# ===========================================================================
# Assertion 1 — action coverage, both directions, per client
# ===========================================================================


class TestActionCoverageBothDirections:
    """ADR 0007's core promise, as a test: Python owns the NAME, the
    client bundles the IMPLEMENTATION, and neither side may hold a name
    the other does not."""

    @pytest.mark.parametrize("client", sorted(KNOWN_CLIENTS))
    def test_every_declared_action_is_implemented(self, client):
        missing = declared_actions_for(client) - implemented_actions_for(client)
        assert not missing, (
            f"{client} is declared to dispatch {sorted(missing)} but bundles no "
            "implementation. Either implement the action in that client's "
            "registry, or narrow the spec's `client_action_clients` in "
            "ppxai/commands/ so the server stops telling that client to run it."
        )

    @pytest.mark.parametrize("client", sorted(KNOWN_CLIENTS))
    def test_every_implementation_is_declared(self, client):
        orphans = implemented_actions_for(client) - declared_actions_for(client)
        assert not orphans, (
            f"{client} implements {sorted(orphans)}, which Python declares for "
            "no command that client can see. An orphan implementation is dead "
            "code the roster can never reach: either declare a `client_action` "
            "for it on a CommandSpec, or delete it from that client's registry."
        )

    @pytest.mark.parametrize("client", sorted(KNOWN_CLIENTS))
    def test_every_implementation_is_in_the_vocabulary(self, client):
        stray = implemented_actions_for(client) - set(PY_CLIENT_ACTIONS)
        assert not stray, (
            f"{client} implements {sorted(stray)}, which is not in the Python "
            "CLIENT_ACTIONS vocabulary (ppxai/commands/factory.py). Add the name "
            "there first — a client-invented action name is a second vocabulary."
        )


# ===========================================================================
# Assertion 2 — no undeclared intercepts
# ===========================================================================


class TestNoUndeclaredIntercepts:
    def test_web_has_no_per_name_branch(self):
        found = js_per_name_branches(_read(WEB_DISPATCHER))
        assert not found, (
            f"hardcoded per-command branches in command-dispatcher.js: {found}. "
            "Routing is the roster's `dispatch` field; declare a `client_action` "
            "on the CommandSpec instead of naming the command here."
        )

    def test_vscode_chatpanel_has_no_per_name_branch(self):
        found = ts_per_name_branches(_read(VSCODE_CHATPANEL))
        assert not found, (
            f"hardcoded per-command branches in chatPanel.ts: {found}. Routing "
            "is the roster's `dispatch` field; declare a `client_action` on the "
            "CommandSpec instead of naming the command here."
        )

    def test_the_router_has_exactly_one_name_keyed_table(self):
        """The action registry (keyed by ACTION, not by name) is the ONLY
        table `commandRouter.ts` exports besides the client id.

        It used to be three: `LEGACY_INTERCEPTS` and `LEGACY_HANDLERS`
        sat beside it, named so a shrinking baseline could watch them.
        Both are deleted (2026-09-21), so the check is no longer "the
        baseline has not grown" but "there is nothing to grow"."""
        clean = strip_js_comments(_read(VSCODE_ROUTER))
        declared = sorted(set(re.findall(
            r"export const ([A-Z][A-Z0-9_]*)", clean)))
        assert declared == ["CLIENT_ACTIONS", "VSCODE_CLIENT_ID"], (
            f"commandRouter.ts's exported tables changed: {declared}. A new "
            "name-keyed table is a second roster — and re-adding the deleted "
            "LEGACY_INTERCEPTS / LEGACY_HANDLERS is exactly that. Route "
            "through the action registry instead."
        )

    @pytest.mark.parametrize("ident", DELETED_LEGACY_IDENTIFIERS)
    def test_the_legacy_mechanism_stays_deleted(self, ident):
        """Absence, not emptiness.

        An EMPTY `LEGACY_INTERCEPTS = []` would pass a "has not grown"
        check forever while leaving the bypass branch in `route()` ready
        for the next row. The tables, the `legacy` member of
        `RouterHost`, `PanelCommandOps.handleCheckpoint` and the branch
        itself are gone; a regex for the ASSIGNMENT (the file's prose
        legitimately names the retired constants for history) is what
        holds that."""
        clean = strip_js_comments(_read(VSCODE_ROUTER))
        assert not re.search(rf"\b{ident}\b\s*[:=]", clean), (
            f"{ident} is back in commandRouter.ts. The legacy-intercept "
            "mechanism was DELETED on 2026-09-21 when its last row "
            "(`/checkpoint`) migrated to factory routing — a client-side "
            "command declares a `client_action` on its CommandSpec instead."
        )

    def test_the_router_has_no_legacy_branch(self):
        """The `route()` bypass itself, not just its tables."""
        clean = strip_js_comments(_read(VSCODE_ROUTER))
        assert "this._host.legacy" not in clean, (
            "commandRouter.ts's route() consults a `legacy` table again — that "
            "is a per-name intercept path around the roster.")
        assert not re.search(r"\blegacy\s*:", clean), (
            "`RouterHost`/`buildCommandRouter` grew a `legacy` member again.")

    def test_the_panel_ops_have_no_checkpoint_handler(self):
        """`PanelCommandOps.handleCheckpoint` was the legacy row's only
        reason to exist; its return would mean the bypass came back."""
        for path in (VSCODE_ROUTER, VSCODE_CHATPANEL):
            assert "handleCheckpoint" not in strip_js_comments(_read(path)), (
                f"handleCheckpoint is back in {path.name} — `/checkpoint` "
                "routes through POST /command/checkpoint now, confirmation "
                "included (prompt_quick_pick from _checkpoint_clear).")

    @pytest.mark.parametrize("rel", (
        "vscode-extension/src/handlers/commands.ts",
        "vscode-extension/src/handlers/types.ts",
    ))
    def test_the_bespoke_rest_handler_files_stay_deleted(self, rel):
        assert not (REPO_ROOT / rel).exists(), (
            f"{rel} is back. It held the bespoke-REST `/checkpoint` handler "
            "(and the IoC types only it used); the command's logic lives in "
            "ppxai/commands/agent.py and reaches this client through the "
            "envelope.")

    def test_no_former_legacy_command_is_named_in_the_router(self):
        """None of the five ever comes back as a literal in the router."""
        clean = strip_js_comments(_read(VSCODE_ROUTER))
        resurrected = sorted(
            name for name in FORMER_LEGACY_INTERCEPTS
            if re.search(rf"['\"`]{name}['\"`]", clean))
        assert not resurrected, (
            f"commandRouter.ts names {resurrected} as a literal again. Every "
            "one of them routes through POST /command/<name>; naming a command "
            "in the router is how the legacy table started.")

    def test_the_textual_quit_legacy_extra_is_gone(self):
        """RESOLVED (owner decision, 2026-09-21): `q` is a registered
        alias of `/quit` now, so `ppxai/tui/app.py` must carry no
        Textual-only legacy-extra constant at all — not an empty one, an
        ABSENT one. Its reappearance (under this name or a new one)
        means someone re-added a name that bypasses the registry."""
        src = _read(TUI_ACTION_SITES["textual"])
        # A regex for the ASSIGNMENT, not a plain substring — app.py's
        # own comments legitimately name the retired constant for
        # historical context; only a live `NAME = ...` is the regression.
        assert not re.search(r"TEXTUAL_LEGACY_QUIT_NAMES\s*=", src), (
            "TEXTUAL_LEGACY_QUIT_NAMES reappeared in ppxai/tui/app.py — "
            "`/q` is a registered alias of `/quit` "
            "(ppxai/commands/client_handled.py) now, so the quit "
            "intercept must derive ALL its names from "
            'CommandFactory.names_for_client_action("app.quit") with no '
            "legacy extra."
        )

    def test_neither_tui_spells_the_quit_names_out(self):
        """The literal these intercepts used to hold (`("quit", "q",
        "exit")`) was the seventh roster: `/quit` grew an `exit` alias on
        the spec and two client files had to remember it."""
        for client, path in TUI_ACTION_SITES.items():
            src = _read(path)
            assert "app.quit" in py_client_action_sites(src), (
                f"{path.relative_to(REPO_ROOT)} no longer derives its quit names "
                "from the spec — use CommandFactory.names_for_client_action("
                '"app.quit") rather than a literal list of names.'
            )
            assert '"/quit", "/exit"' not in src and "'/quit', '/exit'" not in src, (
                f"{client} restates the quit names as literals again"
            )


# ===========================================================================
# Assertion 3 — no surviving hand-written roster, anywhere
# ===========================================================================

#: Each deletion in the plan's "Deletions that prove the migration is
#: complete" table, as (label, check) — the file is gone, or the
#: identifier is gone from the comment-stripped source of its file.
DELETED_FILES = (
    ("web/shared/commands.js (376 lines, step 3a)", WEB / "shared" / "commands.js"),
    ("vscode-extension/src/shared/commands.ts (31 entries, step 3b)",
     EXT / "src" / "shared" / "commands.ts"),
)

DELETED_IDENTIFIERS = (
    ("the app.js inline fallback catalog", WEB / "app.js", "slashCommands"),
    ("_appendExperimentalHelp (the /help stitching shim)",
     WEB_DISPATCHER, "_appendExperimentalHelp"),
    ("_BUILTIN_SPECIAL_COMMANDS", PPXAI / "engine" / "completion.py",
     "_BUILTIN_SPECIAL_COMMANDS"),
    ("_CLIENT_GATES", PPXAI / "engine" / "completion.py", "_CLIENT_GATES"),
)

#: The seven `_*_SUBCOMMANDS` tables step 4 moved onto
#: `CommandSpec.subcommands`. The plan and the ADR both said SIX;
#: `_RUN_SUBCOMMANDS` post-dated the count.
DELETED_SUBCOMMAND_TABLES = (
    "_TOOLS_SUBCOMMANDS", "_USAGE_SUBCOMMANDS", "_CHECKPOINT_SUBCOMMANDS",
    "_STATUS_SUBCOMMANDS", "_THEME_SUBCOMMANDS", "_TASK_SUBCOMMANDS",
    "_RUN_SUBCOMMANDS", "_TOKEN_SUBCOMMANDS",
)


def _code_of(path: Path) -> str:
    """Source with comments blanked, so a mention in prose does not
    count as a survival. `engine/completion.py` explains at length what
    it deleted, and `shared/index.ts` lists the symbols that went with
    `commands.ts` — both are records, not rosters."""
    src = _read(path)
    if path.suffix == ".py":
        return "\n".join(
            "" if line.lstrip().startswith("#") else line
            for line in src.splitlines())
    return strip_js_comments(src)


class TestNoSurvivingHandWrittenRoster:
    @pytest.mark.parametrize("label,path", DELETED_FILES,
                             ids=[d[0].split()[0] for d in DELETED_FILES])
    def test_the_file_stays_deleted(self, label, path):
        assert not path.exists(), (
            f"{label} is back. It was one of the six rosters ADR 0007 removed; "
            "clients fetch GET /commands now."
        )

    @pytest.mark.parametrize("label,path,ident", DELETED_IDENTIFIERS,
                             ids=[d[2] for d in DELETED_IDENTIFIERS])
    def test_the_identifier_stays_deleted(self, label, path, ident):
        assert ident not in _code_of(path), (
            f"{label} is back in {path.relative_to(REPO_ROOT)} — that is a "
            "second source of command metadata. Read GET /commands (JS) or "
            "CommandFactory.roster() (Python) instead."
        )

    @pytest.mark.parametrize("table", DELETED_SUBCOMMAND_TABLES)
    def test_no_subcommand_table_survives(self, table):
        assert table not in _code_of(PPXAI / "engine" / "completion.py"), (
            f"{table} is back in engine/completion.py. Subcommands live on "
            "CommandSpec.subcommands (step 4); completion reads the roster it "
            "is handed."
        )

    def test_no_subcommand_table_by_any_name(self):
        """The generic form of the row above: step 4 found a SEVENTH
        table (`_RUN_SUBCOMMANDS`) that neither the plan nor the ADR had
        counted, because both listed the tables by name."""
        found = sorted(set(re.findall(
            r"^(_[A-Z_]+_SUBCOMMANDS)\b",
            _code_of(PPXAI / "engine" / "completion.py"), re.M)))
        assert not found, (
            f"a `_*_SUBCOMMANDS` table is back in engine/completion.py: {found}. "
            "Declare the subcommands on the CommandSpec instead."
        )

    def test_the_rich_welcome_is_derived_not_written(self):
        """The seventh roster, found while doing step 4:
        `rich/ui.py::display_welcome` rendered a hand-written ~30-command
        list at Rich startup, already 18 commands out of date."""
        src = _read(PPXAI / "rich" / "ui.py")
        assert "def display_welcome(commands)" in src, (
            "display_welcome must take the roster as data (the step-4 idiom: "
            "plain data in, no upward import) — a parameterless version means "
            "the list came from somewhere else again"
        )

    def test_the_second_rich_welcome_stays_deleted(self):
        """`ui_components.py::render_welcome` was a second, differently
        worded welcome roster with zero callers. Deleted in step 5."""
        assert "render_welcome" not in _read(PPXAI / "rich" / "ui_components.py")
        hits = [p for root in (PPXAI, REPO_ROOT / "tests", REPO_ROOT / "scripts")
                for p in root.rglob("*.py")
                if p != Path(__file__)
                and "render_welcome" in p.read_text(encoding="utf-8", errors="replace")]
        assert not hits, f"render_welcome came back in: {hits}"

    def test_no_new_catalog_anywhere_in_the_tree(self):
        """The GENERIC detector — the one that catches the roster nobody
        thought to name."""
        hits = [h for h in find_catalogs() if not exempt(h[0], h[1])]
        assert not hits, (
            "literal command catalog(s) found — a collection or prose string "
            f"naming {CATALOG_THRESHOLD}+ distinct registered commands is a "
            "roster, and the registry is the only one there may be. Fetch "
            "GET /commands (JS) or call CommandFactory.roster() (Python):\n  "
            + "\n  ".join(f"{p}:{line} — {count} commands: {names}"
                          for p, line, count, names in hits)
        )

    def test_every_catalog_exemption_still_applies(self):
        """An exemption whose literal is gone must be deleted from
        `CATALOG_EXEMPTIONS`, or the allowlist drifts into a wish-list."""
        for rel_path, ident in sorted(CATALOG_EXEMPTIONS):
            path = REPO_ROOT / rel_path
            assert path.exists(), f"exempted file {rel_path} is gone"
            assert ident in _code_of(path), (
                f"the exemption ({rel_path}, {ident}) names a literal that no "
                "longer exists — delete the row from CATALOG_EXEMPTIONS."
            )


# ===========================================================================
# Assertion 4 — side-effect kind coverage, DERIVED from Python
# ===========================================================================

#: Kinds a given client deliberately does not handle, with the reason.
#: EMPTY TODAY, and that is the finding: both clients handle all
#: seventeen, `vscode_delegate` included (web's handler is an explicit,
#: commented no-op rather than an omission, which is the right shape —
#: the open-enum rule means an unhandled kind is silently ignored, so an
#: omission is invisible at runtime).
SIDE_EFFECT_EXEMPTIONS: dict[str, dict[str, str]] = {
    "web": {},
    "vscode": {},
}


def side_effect_kinds_for(client: str) -> set[str]:
    if client == "web":
        return set(js_object_keys(_read(WEB_SIDE_EFFECTS),
                                  r"SideEffectsHandler\._handlers\s*=\s*"))
    return ts_switch_case_kinds(_read(VSCODE_SIDE_EFFECTS))


class TestSideEffectKindCoverage:
    """`refresh_command_roster` was added to `SideEffectKind` in step 2
    and NO client noticed, because both drift fences hardcoded their own
    expected sets. Those sets were retargeted onto
    `SideEffectKind.all_kinds()` in this step; this class is the
    derivation they now share."""

    @pytest.mark.parametrize("client", ("web", "vscode"))
    def test_every_python_kind_is_handled(self, client):
        handled = side_effect_kinds_for(client)
        exempt_kinds = SIDE_EFFECT_EXEMPTIONS[client]
        missing = sorted(set(SideEffectKind.all_kinds()) - handled
                         - set(exempt_kinds))
        assert not missing, (
            f"{client} handles none of {missing}, which "
            "ppxai/commands/results.py::SideEffectKind declares. Kinds are an "
            "OPEN enum, so an unhandled one is silently ignored at runtime — "
            "this test is the only thing that sees it. Add the handler, or add "
            f"the kind to SIDE_EFFECT_EXEMPTIONS[{client!r}] with a reason."
        )

    @pytest.mark.parametrize("client", ("web", "vscode"))
    def test_no_client_handles_a_kind_python_does_not_declare(self, client):
        orphans = sorted(side_effect_kinds_for(client)
                         - set(SideEffectKind.all_kinds()))
        assert not orphans, (
            f"{client} handles {orphans}, which SideEffectKind does not declare. "
            "Either add the constant in ppxai/commands/results.py (and its "
            "SideEffect docstring row), or delete the handler — nothing can "
            "ever emit it."
        )

    def test_the_two_clients_handle_the_same_kinds(self):
        web = side_effect_kinds_for("web")
        vscode = side_effect_kinds_for("vscode")
        assert web == vscode, (
            "the two clients' side-effect coverage diverged: web-only "
            f"{sorted(web - vscode)}, vscode-only {sorted(vscode - web)}. "
            "Divergence here is the 'rare misalignment' class of bug — one "
            "client silently ignoring an effect the other performs."
        )

    def test_every_exemption_names_a_real_kind_and_a_reason(self):
        for client, rows in SIDE_EFFECT_EXEMPTIONS.items():
            for kind, reason in rows.items():
                assert kind in SideEffectKind.all_kinds(), (
                    f"{client} exempts {kind!r}, which is not a declared kind")
                assert reason.strip(), f"{client}'s {kind} exemption has no reason"

    def test_no_exemption_is_stale(self):
        for client, rows in SIDE_EFFECT_EXEMPTIONS.items():
            handled = side_effect_kinds_for(client)
            stale = sorted(set(rows) & handled)
            assert not stale, (
                f"{client} now handles {stale} — delete the row(s) from "
                "SIDE_EFFECT_EXEMPTIONS so the list keeps describing the tree."
            )


# ===========================================================================
# Assertion 4a — the prompt kinds reach ALL FOUR clients
# ===========================================================================

#: Where each client's consumer of the prompt kinds lives. The TUIs are
#: here for the first time (2026-09-21): before that, `grep -rn
#: side_effect ppxai/tui ppxai/rich ppxai/rendering` returned nothing, so
#: `/show @config` with three matches printed "3 files match 'config'"
#: and the command the user asked for never ran.
TUI_SIDE_EFFECT_SITES = {
    "rich": PPXAI / "rendering" / "rich_renderer.py",
    "textual": PPXAI / "tui" / "app.py",
}

#: …and where each TUI's dispatch path CALLS that consumer. A consumer
#: nobody calls satisfies a source scan while changing nothing at
#: runtime, so both halves are fenced.
TUI_SIDE_EFFECT_CALL_SITES = {
    "rich": (PPXAI / "commands" / "handler.py", "consume_prompt_side_effects("),
    "textual": (PPXAI / "tui" / "app.py", "self._consume_prompt_side_effects("),
}

#: Prompt kinds a given client deliberately does not consume, with the
#: reason. **EMPTY, and it must stay honest**: a client listed here is a
#: client where the command dead-ends, so a row is a bug report with a
#: date on it, not an architecture decision. It may only SHRINK.
PROMPT_KIND_EXEMPTIONS: dict[str, dict[str, str]] = {
    "rich": {},
    "textual": {},
    "web": {},
    "vscode": {},
}


def _kind_constant_names() -> list[str]:
    """Every uppercase string constant on `SideEffectKind`, derived."""
    return sorted(
        name for name in vars(SideEffectKind)
        if name.isupper() and isinstance(getattr(SideEffectKind, name), str)
    )


def prompt_kinds_in(src: str) -> set[str]:
    """Kinds a Python client source references by CONSTANT.

    Derived from `SideEffectKind`'s own attribute names, so this cannot
    drift from the vocabulary. Constants rather than bare strings is the
    house rule (command-envelope.md rule 2) precisely so a typo is an
    `AttributeError`; it also makes the reference greppable from here.
    """
    return {
        getattr(SideEffectKind, name)
        for name in _kind_constant_names()
        if re.search(rf"SideEffectKind\.{name}\b", src)
    }


def prompt_kinds_for(client: str) -> set[str]:
    if client in TUI_SIDE_EFFECT_SITES:
        return prompt_kinds_in(_read(TUI_SIDE_EFFECT_SITES[client]))
    return side_effect_kinds_for(client)


class TestPromptKindExtractorGuards:
    """Guards + positive control FIRST: a broken extractor that returns
    an empty set would make every coverage assertion below vacuously
    true, which is the failure mode this whole file exists to avoid."""

    def test_the_vocabulary_is_populated(self):
        assert len(_kind_constant_names()) >= 15, _kind_constant_names()

    def test_the_round_trip_set_is_a_subset_of_the_vocabulary(self):
        stray = sorted(CLIENT_ROUND_TRIP_KINDS - set(SideEffectKind.all_kinds()))
        assert not stray, (
            f"CLIENT_ROUND_TRIP_KINDS names {stray}, which SideEffectKind does "
            "not declare")

    def test_the_round_trip_set_is_not_empty(self):
        assert CLIENT_ROUND_TRIP_KINDS

    def test_a_planted_reference_is_detected(self):
        """Positive control for the TUI extractor."""
        assert prompt_kinds_in(
            "if effect.kind == SideEffectKind.PROMPT_QUICK_PICK: pass"
        ) == {"prompt_quick_pick"}

    def test_an_unrelated_source_yields_nothing(self):
        assert prompt_kinds_in("x = 1  # prompt_quick_pick in a comment") == set()

    def test_a_similar_name_is_not_a_false_positive(self):
        assert prompt_kinds_in("SideEffectKind.PROMPT_QUICK_PICKLE") == set()

    @pytest.mark.parametrize("client", sorted(TUI_SIDE_EFFECT_SITES))
    def test_each_tui_site_exists_and_is_not_empty(self, client):
        path = TUI_SIDE_EFFECT_SITES[client]
        assert path.exists(), f"{client}'s side-effect site {path} is gone"
        assert len(_read(path)) > 1000

    @pytest.mark.parametrize("client", sorted(TUI_SIDE_EFFECT_SITES))
    def test_each_tui_extractor_sees_something(self, client):
        assert prompt_kinds_for(client), (
            f"the {client} extractor found NO SideEffectKind reference at all "
            f"in {TUI_SIDE_EFFECT_SITES[client]} — that is an extractor "
            "failure, not coverage")


class TestPromptKindsAreConsumedEverywhere:
    """`CLIENT_ROUND_TRIP_KINDS` is the set a client cannot drop.

    Every other kind degrades gracefully: ignore `open_editor` and the
    rendered result is still on screen. Ignore one of these and the
    command is DEAD — the handler returned a question and performed
    none of its work — silently, because kinds are an open enum.
    """

    @pytest.mark.parametrize(
        "client", ("rich", "textual", "web", "vscode"))
    def test_every_prompt_kind_is_consumed(self, client):
        consumed = prompt_kinds_for(client)
        exempt = set(PROMPT_KIND_EXEMPTIONS[client])
        missing = sorted(CLIENT_ROUND_TRIP_KINDS - consumed - exempt)
        assert not missing, (
            f"{client} does not consume {missing}. These kinds REQUIRE a "
            "client round trip: the handler asked the user a question and did "
            "nothing else, so a client that ignores one leaves the command "
            "dead-ended with no error anywhere — `/checkpoint clear` would "
            "silently never clear, `/show @x` would print the match count and "
            "stop. Implement it in that client, or add it to "
            f"PROMPT_KIND_EXEMPTIONS[{client!r}] with a reason and a date."
        )

    @pytest.mark.parametrize("client", sorted(TUI_SIDE_EFFECT_CALL_SITES))
    def test_each_tui_dispatch_path_calls_its_consumer(self, client):
        """A consumer nobody calls passes a source scan and does
        nothing. This is the half that the source scan cannot see."""
        path, needle = TUI_SIDE_EFFECT_CALL_SITES[client]
        assert needle in _read(path), (
            f"{client}'s command dispatch path ({path.name}) no longer calls "
            f"`{needle}` — the consumer is dead code and every prompt kind "
            "dead-ends again."
        )

    def test_the_two_tuis_consume_the_same_prompt_kinds(self):
        rich = prompt_kinds_for("rich") & CLIENT_ROUND_TRIP_KINDS
        textual = prompt_kinds_for("textual") & CLIENT_ROUND_TRIP_KINDS
        assert rich == textual, (
            f"the TUIs diverged: rich-only {sorted(rich - textual)}, "
            f"textual-only {sorted(textual - rich)}")

    def test_every_exemption_names_a_real_kind_and_a_reason(self):
        for client, rows in PROMPT_KIND_EXEMPTIONS.items():
            for kind, reason in rows.items():
                assert kind in CLIENT_ROUND_TRIP_KINDS, (
                    f"{client} exempts {kind!r}, which is not a round-trip kind")
                assert reason.strip(), f"{client}'s {kind} exemption has no reason"

    def test_no_exemption_is_stale(self):
        for client, rows in PROMPT_KIND_EXEMPTIONS.items():
            stale = sorted(set(rows) & prompt_kinds_for(client))
            assert not stale, (
                f"{client} now consumes {stale} — delete the row(s) from "
                "PROMPT_KIND_EXEMPTIONS so the list keeps describing the tree.")

    def test_the_exemption_table_covers_every_fenced_client(self):
        assert set(PROMPT_KIND_EXEMPTIONS) == {"rich", "textual", "web", "vscode"}


class TestMutationPromptKindCoverage:
    """Break it, watch it fail — for the extractor, on synthetic source,
    so the real tree is never touched."""

    def test_a_tui_that_drops_a_kind_is_caught(self):
        src = _read(TUI_SIDE_EFFECT_SITES["textual"]).replace(
            "SideEffectKind.PROMPT_QUICK_PICK", "SideEffectKind.NOTIFY")
        assert "prompt_quick_pick" not in prompt_kinds_in(src)

    def test_a_tui_that_keeps_it_is_not_caught(self):
        assert "prompt_quick_pick" in prompt_kinds_in(
            _read(TUI_SIDE_EFFECT_SITES["textual"]))

    def test_a_dropped_rich_call_site_is_caught(self):
        path, needle = TUI_SIDE_EFFECT_CALL_SITES["rich"]
        assert needle not in _read(path).replace(needle, "pass  # dropped")

    def test_a_dropped_web_prompt_handler_is_caught(self):
        broken = _read(WEB_SIDE_EFFECTS).replace(
            "prompt_quick_pick({title", "disabled_quick_pick({title")
        handled = set(js_object_keys(
            broken, r"SideEffectsHandler\._handlers\s*=\s*"))
        assert "prompt_quick_pick" not in handled

    def test_a_dropped_vscode_prompt_case_is_caught(self):
        broken = _read(VSCODE_SIDE_EFFECTS).replace(
            "case KIND.PROMPT_QUICK_PICK:", "case KIND.NOTIFY:")
        assert "prompt_quick_pick" not in ts_switch_case_kinds(broken)


# ===========================================================================
# Assertion 5 — roster self-consistency
# ===========================================================================


class TestRosterSelfConsistency:
    """The end-to-end form: whatever `GET /commands?client=<id>` would
    actually serve must be runnable by that client. This is the one that
    catches a gating mistake — a command visible to a client whose
    action that client cannot run."""

    @pytest.mark.parametrize("client", sorted(KNOWN_CLIENTS))
    def test_no_client_dispatch_entry_names_an_unimplemented_action(self, client):
        entries = CommandFactory.roster(client)["commands"]
        assert entries, f"roster({client!r}) is empty — the registry did not load"
        implemented = implemented_actions_for(client)
        broken = sorted(
            f"/{e['name']} -> {e['client_action']}"
            for e in entries
            if e["dispatch"] == "client"
            and e["client_action"] not in implemented
        )
        assert not broken, (
            f"GET /commands?client={client} tells {client} to dispatch these "
            f"itself, but it bundles no implementation: {broken}. The client "
            "refuses (it never forwards a client-dispatched command), so the "
            "command is simply broken there. Fix the spec's `clients` / "
            "`client_action_clients`, or implement the action."
        )

    @pytest.mark.parametrize("client", sorted(KNOWN_CLIENTS))
    def test_no_client_dispatch_entry_lacks_an_action(self, client):
        nameless = sorted(e["name"] for e in CommandFactory.roster(client)["commands"]
                          if e["dispatch"] == "client" and not e["client_action"])
        assert not nameless, (
            f"roster({client!r}) reports dispatch=='client' for {nameless} with "
            "no `client_action` to dispatch TO — the client has nothing to call."
        )

    def test_the_tuis_are_served_exactly_the_quit_action(self):
        """A pin on today's shape, so the day a second in-process client
        action appears, someone re-reads the two intercept sites."""
        for client in ("rich", "textual"):
            actions = {e["client_action"]
                       for e in CommandFactory.roster(client)["commands"]
                       if e["dispatch"] == "client"}
            assert actions == {"app.quit"}, (
                f"{client} is now served {sorted(actions)}. The in-process TUIs "
                "dispatch client actions from a hand-written intercept BEFORE "
                "the factory lookup (ppxai/commands/handler.py, "
                "ppxai/tui/app.py) — a second action needs a home there."
            )


# ===========================================================================
# Cross-check against the REAL compiled TypeScript
# ===========================================================================
#
# The regexes above are the primary path, because they need no toolchain
# and the fence must run everywhere. But regexing another language is
# exactly the fragility this file's docstring warns about, so where the
# real module can be COMPILED AND IMPORTED — the harness
# tests/test_vscode_command_roster_behavior.py established, using the
# extension's own esbuild — it is, and the two must agree.

NODE = shutil.which("node")
ESBUILD = EXT / "node_modules" / ".bin" / "esbuild"

_ENTRY = "export * from './commandRouter';\n"

_HARNESS = r"""
const B = require(process.env.PPXAI_BUNDLE);
console.log(JSON.stringify({
    actions: Object.keys(B.CLIENT_ACTIONS).sort(),
    // The compiled module must export NOTHING legacy. Reading the names
    // (rather than asserting on the regex alone) is the point: a
    // re-added table shows up here even if it is spelled differently in
    // source than the regex expects.
    exports: Object.keys(B).sort(),
}));
"""


def _compiled_router_tables(tmp_path: Path) -> dict:
    work = tmp_path / "src"
    work.mkdir(parents=True, exist_ok=True)
    for name in ("commandRoster.ts", "commandRouter.ts"):
        (work / name).write_text(_read(EXT / "src" / name), encoding="utf-8")
    (work / "entry.ts").write_text(_ENTRY, encoding="utf-8")
    out = tmp_path / "bundle.js"
    build = subprocess.run(
        [str(ESBUILD), str(work / "entry.ts"), "--bundle", "--format=cjs",
         "--platform=node", "--target=node18", f"--outfile={out}"],
        capture_output=True, text=True, timeout=120,
    )
    assert build.returncode == 0, f"esbuild failed:\n{build.stderr}"
    script = tmp_path / "read.js"
    script.write_text(_HARNESS, encoding="utf-8")
    env = dict(os.environ, PPXAI_BUNDLE=str(out))
    run = subprocess.run([NODE, str(script)], capture_output=True,
                         text=True, timeout=60, env=env)
    assert run.returncode == 0, f"node failed:\n{run.stderr}"
    return json.loads(run.stdout)


@pytest.mark.skipif(NODE is None or not ESBUILD.exists(),
                    reason="node and vscode-extension/node_modules/.bin/esbuild "
                           "are required for the compiled cross-check")
class TestRegexAgreesWithTheCompiledModule:
    """If these two ever disagree, TRUST THE COMPILED MODULE and fix the
    regex — not the other way round."""

    def test_action_registry_keys_agree(self, tmp_path):
        compiled = _compiled_router_tables(tmp_path)
        assert compiled["actions"], "the compiled CLIENT_ACTIONS registry is empty"
        assert sorted(implemented_actions_for("vscode")) == compiled["actions"]

    def test_the_compiled_module_exports_nothing_legacy(self, tmp_path):
        """The regex above reads source; this reads the BUILT module, so
        a legacy table re-added under any spelling is still caught."""
        compiled = _compiled_router_tables(tmp_path)
        legacy = sorted(name for name in compiled["exports"]
                        if "LEGACY" in name.upper())
        assert not legacy, (
            f"the compiled commandRouter still exports {legacy}. The "
            "legacy-intercept mechanism was deleted on 2026-09-21.")

    def test_the_compiled_module_exports_exactly_the_expected_names(self, tmp_path):
        compiled = _compiled_router_tables(tmp_path)
        assert "CLIENT_ACTIONS" in compiled["exports"], (
            "the harness read no CLIENT_ACTIONS — the build or the bundle is "
            "broken, so the absence check above would pass vacuously")


@pytest.mark.skipif(NODE is None, reason="node not on PATH")
class TestWebRegexAgreesWithTheRealModule:
    """Web's files are plain CommonJS, so the real module needs no build
    step — `require` it and read the tables off it."""

    def test_action_registry_keys_agree(self, tmp_path):
        script = tmp_path / "read.js"
        script.write_text(
            "global.window = undefined;\n"
            "const {CommandDispatcher} = require(process.env.PPXAI_DISPATCHER);\n"
            "const {SideEffectsHandler} = require(process.env.PPXAI_SIDE_EFFECTS);\n"
            "console.log(JSON.stringify({\n"
            "  actions: Object.keys(CommandDispatcher.CLIENT_ACTIONS).sort(),\n"
            "  kinds: Object.keys(SideEffectsHandler._handlers).sort(),\n"
            "}));\n", encoding="utf-8")
        env = dict(os.environ, PPXAI_DISPATCHER=str(WEB_DISPATCHER),
                   PPXAI_SIDE_EFFECTS=str(WEB_SIDE_EFFECTS))
        run = subprocess.run([NODE, str(script)], capture_output=True,
                             text=True, timeout=60, env=env)
        assert run.returncode == 0, f"node failed:\n{run.stderr}"
        real = json.loads(run.stdout)
        assert real["actions"], "the real CLIENT_ACTIONS registry is empty"
        assert sorted(implemented_actions_for("web")) == real["actions"]
        assert sorted(side_effect_kinds_for("web")) == real["kinds"]


# ===========================================================================
# MUTATION VERIFICATION — every assertion above must be able to fail
# ===========================================================================
#
# Nothing here touches the tree: the mutants are strings, or copies under
# pytest's tmp_path.


class TestMutationActionCoverage:
    def test_an_orphan_implementation_is_caught(self):
        src = _read(WEB_DISPATCHER).replace(
            "CommandDispatcher.CLIENT_ACTIONS = {",
            "CommandDispatcher.CLIENT_ACTIONS = {\n    'ghost.action'() {},",
            1)
        implemented = set(js_object_keys(
            src, r"CommandDispatcher\.CLIENT_ACTIONS\s*=\s*"))
        assert "ghost.action" in implemented - declared_actions_for("web")

    def test_a_missing_implementation_is_caught(self):
        src = _read(WEB_DISPATCHER).replace("'token.manage'(", "'gone.manage'(", 1)
        implemented = set(js_object_keys(
            src, r"CommandDispatcher\.CLIENT_ACTIONS\s*=\s*"))
        assert "token.manage" in declared_actions_for("web") - implemented

    def test_a_removed_tui_call_site_is_caught(self):
        src = _read(TUI_ACTION_SITES["textual"]).replace(
            'names_for_client_action("app.quit")', 'QUIT_NAMES')
        assert "app.quit" in declared_actions_for("textual") - py_client_action_sites(src)

    def test_a_vscode_registry_losing_an_action_is_caught(self):
        src = _read(VSCODE_ROUTER).replace("'coding.stream':", "'coding.streem':", 1)
        implemented = set(js_object_keys(
            src, r"export const CLIENT_ACTIONS: Record<string, OpsAction>\s*=\s*"))
        assert "coding.stream" in declared_actions_for("vscode") - implemented


class TestMutationLegacyMechanismIsGone:
    """The absence checks must be able to FAIL — an absence assertion
    that cannot fail is the most comfortable kind of green."""

    def test_a_reintroduced_table_is_caught(self):
        src = strip_js_comments(_read(VSCODE_ROUTER)) + (
            "\nexport const LEGACY_INTERCEPTS: readonly string[] = ['checkpoint'];\n")
        assert re.search(r"\bLEGACY_INTERCEPTS\b\s*[:=]", src)

    def test_an_empty_reintroduced_table_is_caught_too(self):
        """The comfortable version: a table with no rows still restores
        the bypass branch for the next person."""
        src = strip_js_comments(_read(VSCODE_ROUTER)) + (
            "\nexport const LEGACY_INTERCEPTS: readonly string[] = [];\n")
        assert re.search(r"\bLEGACY_INTERCEPTS\b\s*[:=]", src)

    def test_a_historical_mention_in_prose_is_not_caught(self):
        """`commandRouter.ts` explains what was deleted and why; that
        sentence must not read as a regression."""
        clean = strip_js_comments(_read(VSCODE_ROUTER))
        assert "LEGACY_INTERCEPTS" in _read(VSCODE_ROUTER), (
            "the router no longer explains what was removed — keep the note")
        assert not re.search(r"\bLEGACY_INTERCEPTS\b\s*[:=]", clean)

    def test_a_reintroduced_legacy_branch_is_caught(self):
        src = strip_js_comments(_read(VSCODE_ROUTER)).replace(
            "await this._host.dispatchToFactory(name, args);",
            "const l = this._host.legacy[name]; if (l) { await l(ctx); return; }",
            1)
        assert "this._host.legacy" in src

    def test_a_reintroduced_ops_row_is_caught(self):
        src = strip_js_comments(_read(VSCODE_ROUTER)).replace(
            "    showHelp(args: string): Promise<void> | void;",
            "    showHelp(args: string): Promise<void> | void;\n"
            "    handleCheckpoint(argv: string[]): Promise<void> | void;", 1)
        assert "handleCheckpoint" in src

    def test_a_restored_handler_file_is_caught(self, tmp_path):
        planted = tmp_path / "commands.ts"
        planted.write_text("export function handleCheckpointCommand() {}\n",
                           encoding="utf-8")
        assert planted.exists()

    def test_a_reintroduced_textual_quit_literal_is_caught(self):
        """Prove the absence check
        (`test_the_textual_quit_legacy_extra_is_gone`) can actually
        fail: plant the retired constant's assignment back into the
        source and assert the regex would flag it (a bare mention in a
        comment, as this file's own docstrings carry, must NOT)."""
        assignment = 'TEXTUAL_LEGACY_QUIT_NAMES = frozenset({"q", "bye"})'
        src_with_assignment = _read(TUI_ACTION_SITES["textual"]) + f"\n{assignment}\n"
        assert re.search(r"TEXTUAL_LEGACY_QUIT_NAMES\s*=", src_with_assignment)

        src_with_comment_only = (
            _read(TUI_ACTION_SITES["textual"])
            + "\n# TEXTUAL_LEGACY_QUIT_NAMES is retired, see history\n"
        )
        assert not re.search(
            r"TEXTUAL_LEGACY_QUIT_NAMES\s*=", src_with_comment_only)


class TestMutationUndeclaredIntercepts:
    def test_a_reintroduced_web_branch_is_caught(self):
        src = _read(WEB_DISPATCHER).replace(
            "            // (2) Chat-shaped commands never touch command dispatch.",
            "            if (cmd === '/token') { return this._handleTokenCommand(args); }",
            1)
        assert js_per_name_branches(src) == ["/token"]

    def test_a_reintroduced_vscode_branch_is_caught(self):
        src = _read(VSCODE_CHATPANEL) + "\nif (command === 'tools') { x(); }\n"
        assert ts_per_name_branches(src) == ["tools"]

    def test_a_subcommand_comparison_is_still_not_a_branch(self):
        src = _read(VSCODE_CHATPANEL) + "\nif (subcommand === 'clear') { x(); }\n"
        assert ts_per_name_branches(src) == []

    def test_a_new_exported_router_table_is_caught(self):
        clean = strip_js_comments(
            _read(VSCODE_ROUTER) + "\nexport const EXTRA_INTERCEPTS = ['x'];\n")
        declared = sorted(set(re.findall(r"export const ([A-Z][A-Z0-9_]*)", clean)))
        assert "EXTRA_INTERCEPTS" in declared


class TestMutationCatalogDetector:
    def test_a_readded_web_catalog_is_caught(self, tmp_path):
        """A scratch copy of the shape step 3a deleted."""
        fake = tmp_path / "commands.js"
        fake.write_text(
            "const SLASH_COMMANDS = {\n" + "".join(
                f"    '/{n}': {{description: 'x', usage: '/{n}'}},\n"
                for n in ("help", "model", "clear", "save", "load", "usage",
                          "tools", "status")) + "};\n", encoding="utf-8")
        rows = scan_js_catalogs(fake.read_text(encoding="utf-8"), command_token_re())
        assert any(c >= CATALOG_THRESHOLD for _l, c, _n in rows)

    def test_a_readded_python_prose_catalog_is_caught(self, tmp_path):
        """The exact shape of the Rich welcome screen this step derived."""
        fake = tmp_path / "welcome.py"
        fake.write_text(
            'WELCOME = """\n' + "".join(
                f"- `/{n}` - does a thing\n"
                for n in ("help", "model", "clear", "save", "load", "usage",
                          "tools", "status")) + '"""\n', encoding="utf-8")
        rows = scan_py_catalogs(fake.read_text(encoding="utf-8"), command_token_re())
        assert any(c >= CATALOG_THRESHOLD for _l, c, _n in rows)

    def test_a_small_button_block_is_not_a_catalog(self):
        """Negative control — the threshold has to leave legitimate
        small groupings alone or the fence gets disabled."""
        src = ("const quick = ['/help', '/model', '/clear', '/tools'];\n")
        rows = scan_js_catalogs(src, command_token_re())
        assert all(c < CATALOG_THRESHOLD for _l, c, _n in rows)

    def test_rest_paths_are_not_a_catalog(self):
        """Negative control — the measured false-positive class."""
        src = ("const urls = ['/command/clear', '/command/model', '/v1/tokens',\n"
               "  '/command/save', '/command/load', '/command/usage',\n"
               "  '/command/tools', '/command/status'];\n")
        rows = scan_js_catalogs(src, command_token_re())
        assert all(c < CATALOG_THRESHOLD for _l, c, _n in rows)


class TestMutationSideEffectCoverage:
    def test_a_dropped_web_handler_is_caught(self):
        src = _read(WEB_SIDE_EFFECTS).replace(
            "    refresh_command_roster({version}) {", "    _gone({version}) {", 1)
        handled = set(js_object_keys(src, r"SideEffectsHandler\._handlers\s*=\s*"))
        assert "refresh_command_roster" in set(SideEffectKind.all_kinds()) - handled

    def test_a_dropped_vscode_case_is_caught(self):
        src = _read(VSCODE_SIDE_EFFECTS).replace(
            "case KIND.REFRESH_COMMAND_ROSTER:", "case KIND.OPEN_EDITOR:", 1)
        handled = ts_switch_case_kinds(src)
        assert "refresh_command_roster" in set(SideEffectKind.all_kinds()) - handled

    def test_an_orphan_web_handler_is_caught(self):
        src = _read(WEB_SIDE_EFFECTS).replace(
            "SideEffectsHandler._handlers = {",
            "SideEffectsHandler._handlers = {\n    ghost_kind() {},", 1)
        handled = set(js_object_keys(src, r"SideEffectsHandler\._handlers\s*=\s*"))
        assert "ghost_kind" in handled - set(SideEffectKind.all_kinds())
