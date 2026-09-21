"""
CompletionProvider — client-agnostic autocomplete engine.

Extracts the completion logic from Rich TUI's `PPXAICompleter` into a
reusable module that all four clients (Rich, Textual, Web, VSCode) can
consume — either in-process (Rich, Textual) or via the `POST /complete`
server endpoint (Web, VSCode).

Completion sources:

1. **Slash commands** — from the ROSTER the caller hands in: the plain
   data `CommandFactory.roster(client)["commands"]` returns (see ADR 0007
   step 4). This module imports nothing from `ppxai.commands`; the caller
   owns the registry and has already filtered the roster for its client,
   so what arrives here is what that client may see. No roster (or an
   empty one) means no slash-command completions — paths and @refs still
   work.

2. **Path arguments** — for commands like `/attach`, `/cd`, `/ls`, `/show`
   etc. Shell-style directory traversal with per-command file/dir filters.

3. **Subcommand completion** — the FIRST level is data: every roster
   entry carries its declared `subcommands`, so `/tools en` → `enable`
   needs no table here (ADR 0007 step 4 deleted the seven hand-written
   `_*_SUBCOMMANDS` tables). What stays is behaviour the flat
   declaration cannot express: second-level arguments (`/usage show
   session`, `/checkpoint backend git`, `/theme emoji on`, `/tools help
   <tool>`, `/task respond <id> approve`) and genuinely live sources
   (`/model` ids, `/provider` ids, `/theme` names, `/task|/run` run ids).

4. **@file + @context references** — `@git`, `@tree`, `@clipboard`, `@url`
   plus fuzzy-match files in the working directory.

Each source returns `CompletionItem` dicts with a stable JSON-serializable
schema so the server route can relay them unchanged to HTTP clients.

All four clients consume the same schema:
    {
      "text":          str,   # text to insert
      "display":       str,   # what to show in the dropdown
      "description":   str,   # hover/meta text
      "kind":          str,   # "command"|"alias"|"dir"|"file"|"file_ref"
                              # |"context_ref"|"subcommand"|"tool"|"model"
                              # |"provider"|"theme"
      "replace_start": int,   # negative offset from cursor: replace last
                              # |replace_start| chars with `text`
    }
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from ..config import PROVIDERS, get_provider_config

# Commands that accept path arguments, and what kinds of entries make
# sense to complete for each.
_PATH_ARG_COMMANDS: dict[str, dict[str, bool]] = {
    "attach":  {"include_files": True,  "include_dirs": True},
    "show":    {"include_files": True,  "include_dirs": True},
    "preview": {"include_files": True,  "include_dirs": True},
    "cd":      {"include_files": False, "include_dirs": True},
    "tree":    {"include_files": False, "include_dirs": True},
    "ls":      {"include_files": True,  "include_dirs": True},
}

# Directories to skip in @file scanning
_IGNORE_DIRS = frozenset({
    ".git", "node_modules", "__pycache__", ".venv", "venv",
    ".tox", "dist", "build", ".eggs", ".mypy_cache",
})

# Context-provider shortcuts — handled by ContextInjector, not the
# filesystem. They appear in the @ dropdown alongside file refs so
# users discover them without having to remember the list.
_CONTEXT_PROVIDERS: list[tuple[str, str]] = [
    ("@git",       "Include git diff (staged + unstaged)"),
    ("@tree",      "Include project directory structure"),
    ("@clipboard", "Include clipboard text content"),
    ("@url",       "Fetch and include URL content"),
]

# Second-level argument tables. The FIRST subcommand level moved onto
# `CommandSpec.subcommands` in ADR 0007 step 4 — the seven
# `_*_SUBCOMMANDS` tables that used to live here (tools, usage,
# checkpoint, status, theme, task, run) were the last hand-written
# roster in the codebase, and completion now reads the caller's roster
# instead. What remains below is what a flat `list[tuple[str, str]]`
# declaration cannot carry: the values of a SECOND argument, and
# suggestions whose source is a live registry rather than a declaration.

_USAGE_DISPLAY_MODES: list[tuple[str, str]] = [
    ("session",  "Status line shows session totals"),
    ("provider", "Status line shows current provider totals"),
    ("model",    "Status line shows current model totals"),
    ("off",      "Hide usage from status line"),
]

_CHECKPOINT_BACKENDS: list[tuple[str, str]] = [
    ("git",  "Use git commits"),
    ("file", "Use file snapshots"),
    ("auto", "Auto-detect best backend"),
    ("none", "Disable checkpoints"),
]

_THEME_NAMES: list[tuple[str, str]] = [
    ("catppuccin-mocha", "Catppuccin Mocha"),
    ("dracula",          "Dracula"),
    ("tokyo-night",      "Tokyo Night"),
    ("nord",             "Nord"),
    ("gruvbox",          "Gruvbox"),
    ("solarized-dark",   "Solarized Dark"),
    ("solarized-light",  "Solarized Light"),
    ("monokai",          "Monokai"),
    ("material",         "Material"),
    ("textual-dark",     "Textual Dark (default)"),
    ("textual-light",    "Textual Light"),
    ("tron-legacy",      "Tron Legacy (cyan/orange)"),
    ("matrix",           "Matrix (green-on-black)"),
]

_EMOJI_OPTIONS: list[tuple[str, str]] = [
    ("on",  "Show original emojis"),
    ("off", "Convert to text symbols"),
]

# Which run statuses make sense as the <id> argument of each /task verb.
# None = any run (inspection verbs work on everything, incl. finalized).
# Aliases (show/open/ack) complete ids too — typed by muscle memory.
_TASK_ID_VERB_STATUSES: dict[str, frozenset | None] = {
    "respond": frozenset({"waiting"}),
    "collect": frozenset({"completed_pending_ack"}),
    "ack":     frozenset({"completed_pending_ack"}),
    "resume":  frozenset({"interrupted", "cancelled"}),
    "cancel":  frozenset({"pending", "running", "waiting", "cancelling"}),
    "get":     None,
    "show":    None,
    "open":    None,
    "watch":   None,
}

_TASK_RESPOND_ANSWERS: list[tuple[str, str]] = [
    ("approve", "Approve the parked request"),
    ("deny",    "Deny the parked request"),
]


# =============================================================================
# Roster access — plain data, handed in by the caller
# =============================================================================
#
# ADR 0007 step 4. The roster is `CommandFactory.roster(client)["commands"]`:
# one dict per CANONICAL command, ALREADY filtered for the client that asked.
# This module consumes the following keys and nothing else, so any producer of
# the same shape works:
#
#     name         str                     canonical name, no leading slash
#     aliases      list[str]               alternative names, no slash
#     description  str
#     hidden       bool                    not offered in completion
#     subcommands  list[{name, description, ...}]   first-level arguments
#
# Deliberately NO fallback: there is no `roster=None` branch that reaches for
# `CommandFactory`, and no lazy import. A fallback would re-create the
# `engine -> commands` edge this step exists to remove, and hide it behind a
# branch nothing exercises.


def _lookup(
    roster: list[dict[str, Any]] | None, typed: str
) -> dict[str, Any] | None:
    """Resolve a typed command name or ALIAS to its roster entry.

    Replaces `CommandFactory.get(typed)` — same resolution (canonical
    first, then aliases), read off the data instead of the registry.
    """
    if not roster:
        return None
    for entry in roster:
        if entry.get("name") == typed:
            return entry
    for entry in roster:
        if typed in (entry.get("aliases") or ()):
            return entry
    return None


def _subcommand_pairs(entry: dict[str, Any] | None) -> list[tuple[str, str]]:
    """`[{name, description, ...}]` from the roster → `(name, description)`.

    The roster publishes subcommands as dicts (they carry `sensitive`
    too); every table-filtering helper here speaks pairs, which is also
    the shape `CommandSpec.subcommands` declares.
    """
    if entry is None:
        return []
    return [
        (str(sub.get("name", "")), str(sub.get("description", "")))
        for sub in (entry.get("subcommands") or ())
    ]


def complete(
    buffer: str,
    cursor: int = -1,
    *,
    roster: list[dict[str, Any]] | None,
    working_dir: str | None = None,
    current_provider: str | None = None,
    tool_names: list[tuple[str, str]] | None = None,
    agent_runs: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Compute completions for a given input buffer + cursor position.

    This is the single entry point for all completion requests. Clients
    call it directly (Rich, Textual) or via the `POST /complete` server
    route (Web, VSCode).

    Args:
        buffer: The full text the user has typed so far.
        cursor: Cursor position (0-indexed). -1 means end-of-buffer.
        working_dir: Working directory for path completions. Falls back
                     to `os.getcwd()` if not provided.
        current_provider: Active provider id, used by `/model <name>`
                          completion to pick the right model list. When
                          omitted, `/model` returns no results.
        tool_names: Optional list of (tool_name, description) pairs used
                    by `/tools help <tool>` completion. Server and Rich
                    pass `engine_client.tool_manager.list_tools()`.
        agent_runs: Optional snapshot of agent runs for `/task <verb> <id>`
                    completion — dicts with {id, status, task, kind,
                    resumable}, newest-first. Only the server can supply
                    this (the AgentRunRegistry is server-side state; the
                    in-process TUIs have no channel to it — T8b parked),
                    so callers without it simply get no run-id suggestions.

    Keyword-only and REQUIRED (ADR 0007 step 4):
        roster: The command roster as plain data —
                `CommandFactory.roster(<this client>)["commands"]`, read
                by the CALLER, which owns the command layer. It arrives
                already filtered for that client, so client gating is
                structural here: a command the client may not see is
                simply not in the data, and there is no `client`
                parameter left to disagree with it. `None` or `[]` is a
                legitimate value meaning "no registry available" — no
                slash-command or subcommand completions, while path and
                @file completion still work. It has no DEFAULT on
                purpose: with three callers, a forgotten roster would be
                a silent empty dropdown, whereas a missing argument is a
                TypeError naming the call site.

    Returns:
        List of completion item dicts with a stable JSON schema
        (see module docstring).
    """
    if cursor < 0:
        cursor = len(buffer)
    text = buffer[:cursor]
    wd = working_dir or os.getcwd()
    tools = tool_names or []

    # @ completion — context providers + @file refs. Takes priority
    # when @ is present anywhere in the visible text.
    at_pos = text.rfind("@")
    if at_pos >= 0:
        query = text[at_pos + 1:]
        return _complete_at_query(query, wd, replace_len=len(text) - at_pos)

    if not text.startswith("/"):
        return []

    # Arguments present → subcommand, path-arg, or dynamic completion
    space_idx = text.find(" ")
    if space_idx > 0:
        return _complete_slash_args(
            text, space_idx, wd, current_provider, tools,
            agent_runs or [], roster,
        )

    # Bare command name
    return _complete_commands(text, roster)


# =============================================================================
# Command name completion
# =============================================================================


def _complete_commands(
    prefix: str, roster: list[dict[str, Any]] | None
) -> list[dict[str, Any]]:
    """Complete slash command names from the roster the caller handed in.

    One entry per canonical command, with its aliases as a FIELD — so
    the alias items are expanded here rather than arriving as rows
    (ADR 0007 step 4; before it this read
    `CommandFactory.iter_completion_specs()` and applied the client gate
    itself). Behaviour is unchanged: canonicals and aliases, hidden
    commands skipped, alias descriptions annotated, sorted by text.

    An absent roster yields nothing: completion offers no slash commands
    rather than reaching for a registry it must not import.
    """
    items: list[dict[str, Any]] = []
    prefix_lower = prefix.lower()

    for entry in roster or ():
        # Client gating (ADR 0007 step 1b, structural since step 4): a
        # command gated to other clients never reaches this loop — the
        # caller asked the registry for ITS client's roster. An
        # unfiltered list taught users to type commands that answered
        # "Unknown command" everywhere else (Item 40 VSCode trial,
        # 2026-07-12).
        if entry.get("hidden"):
            continue
        canonical = str(entry.get("name", ""))
        if not canonical:
            continue
        description = str(entry.get("description", ""))

        candidate = f"/{canonical}"
        if candidate.lower().startswith(prefix_lower):
            items.append({
                "text": candidate,
                "display": candidate,
                "description": description,
                "kind": "command",
                "replace_start": -len(prefix),
            })

        for alias in entry.get("aliases") or ():
            candidate = f"/{alias}"
            if not candidate.lower().startswith(prefix_lower):
                continue
            items.append({
                "text": candidate,
                "display": candidate,
                "description": f"{description} (alias for /{canonical})",
                "kind": "alias",
                "replace_start": -len(prefix),
            })

    items.sort(key=lambda e: e["text"])
    return items


# =============================================================================
# Slash arg dispatch
# =============================================================================


def _complete_slash_args(
    text: str,
    space_idx: int,
    wd: str,
    current_provider: str | None,
    tool_names: list[tuple[str, str]],
    agent_runs: list[dict[str, Any]],
    roster: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    """Route `/cmd ...` to the right arg completer.

    Resolves aliases against the roster (so `/att` completes paths just
    like `/attach`) before dispatching — `CommandFactory.get()` did that
    until ADR 0007 step 4. Unknown commands keep the name as typed and
    fall through to the path-arg table, then to an empty list.

    The FIRST subcommand level is generic: whatever the entry declares
    is what gets offered. The branches below are the completions that a
    flat declaration cannot express — second-level arguments, and
    suggestions computed from live state.
    """
    typed_cmd = text[1:space_idx]
    entry = _lookup(roster, typed_cmd)
    canonical = str(entry["name"]) if entry is not None else typed_cmd
    args_region = text[space_idx + 1:]
    subcommands = _subcommand_pairs(entry)

    # Commands whose arguments need more than the declared table
    if canonical == "tools":
        return _complete_tools(args_region, tool_names, subcommands)
    if canonical == "usage":
        return _complete_usage(args_region, subcommands)
    if canonical == "checkpoint":
        return _complete_checkpoint(args_region, subcommands)
    if canonical == "theme":
        return _complete_theme(args_region, subcommands)
    if canonical == "model":
        return _complete_model(args_region, current_provider)
    if canonical == "provider":
        return _complete_provider(args_region)
    if canonical == "task":
        # A command this client cannot dispatch is not in its roster, so
        # there is nothing to suggest for it either — the explicit
        # `_client_allows("task", client)` gate this used to carry is
        # now structural (ADR 0007 step 4).
        if entry is None:
            return []
        return _complete_task(args_region, agent_runs, subcommands)
    if canonical == "run":
        # U3: same machinery, the entry's own verb table, oneshot ids.
        if entry is None:
            return []
        return _complete_task(
            args_region, agent_runs, subcommands, kind="oneshot",
        )

    # Path arg commands
    path_opts = _PATH_ARG_COMMANDS.get(canonical)
    if path_opts is not None:
        _, token = _last_ws_token(args_region)
        return _complete_path(
            token, wd,
            include_files=path_opts["include_files"],
            include_dirs=path_opts["include_dirs"],
        )

    # Everything else: the declared first-level subcommands, if any.
    # `/token` came through here first (ADR 0007 step 1b) and is now
    # simply one of many — no per-command code for a command whose
    # completion IS its declaration.
    completed, token = _split_args(args_region)
    if not completed and subcommands:
        return _filter_table(token, subcommands, "subcommand")

    return []


# =============================================================================
# Subcommand completion helpers
# =============================================================================


def _split_args(args_region: str) -> tuple[list[str], str]:
    """Split `/cmd a b c` args region into (completed_tokens, active_token).

    The active_token is what the user is currently typing. Completed
    tokens are the whitespace-delimited words before it. A trailing
    space means the active_token is empty (ready for next arg).

    Examples:
        ""           → ([], "")
        "help"       → ([], "help")
        "help "      → (["help"], "")
        "help calc"  → (["help"], "calc")
    """
    if not args_region:
        return [], ""
    parts = args_region.split()
    if args_region.endswith((" ", "\t")):
        return parts, ""
    if not parts:
        return [], ""
    return parts[:-1], parts[-1]


def _filter_table(
    token: str,
    table: list[tuple[str, str]],
    kind: str,
) -> list[dict[str, Any]]:
    """Filter a (name, description) table by prefix and wrap as items."""
    token_lower = token.lower()
    return [
        {
            "text": name,
            "display": name,
            "description": desc,
            "kind": kind,
            "replace_start": -len(token),
        }
        for name, desc in table
        if not token_lower or name.lower().startswith(token_lower)
    ]


def _complete_tools(
    args_region: str,
    tool_names: list[tuple[str, str]],
    subcommands: list[tuple[str, str]],
) -> list[dict[str, Any]]:
    """`/tools <subcmd>` (declared) + `/tools help <tool>` (live tools)."""
    completed, token = _split_args(args_region)

    if not completed:
        return _filter_table(token, subcommands, "subcommand")

    if len(completed) == 1 and completed[0].lower() == "help":
        return _filter_table(token, tool_names, "tool")

    return []


def _complete_task(
    args_region: str,
    agent_runs: list[dict[str, Any]],
    subcommands: list[tuple[str, str]],
    *,
    kind: str = "task",
) -> list[dict[str, Any]]:
    """`/task <verb>` + status-aware `/task <verb> <run_id>` completion.

    The verb determines which runs make sense as its id argument
    (`_TASK_ID_VERB_STATUSES`): `collect` (alias `ack`) only offers 📬
    held results, `respond` only ✋ parked runs, `resume` only
    interrupted/cancelled (and resumable) ones, `cancel` only in-flight
    ones; the inspection verbs (get/watch + show/open aliases) offer
    everything. Suggestions carry the run's task text so users pick by
    meaning, not by hex id. A non-verb first token is a direct-launch
    prompt (U2) — no completion offered there.
    """
    completed, token = _split_args(args_region)

    if not completed:
        return _filter_table(token, subcommands, "subcommand")

    verb = completed[0].lower()

    # `/task respond <id> <answer>` — the third token is the answer word.
    if verb == "respond" and len(completed) == 2:
        return _filter_table(token, _TASK_RESPOND_ANSWERS, "subcommand")

    if len(completed) != 1 or verb not in _TASK_ID_VERB_STATUSES:
        return []

    statuses = _TASK_ID_VERB_STATUSES[verb]
    token_lower = token.lower()
    items: list[dict[str, Any]] = []
    for run in agent_runs:
        run_id = str(run.get("id", ""))
        status = str(run.get("status", ""))
        if not run_id:
            continue
        # U3: each family only offers its own kind's ids (legacy snapshots
        # without a kind read as "task").
        if (run.get("kind") or "task") != kind:
            continue
        if statuses is not None and status not in statuses:
            continue
        if verb == "resume" and not run.get("resumable", False):
            continue
        if token_lower and not run_id.lower().startswith(token_lower):
            continue
        task_text = str(run.get("task", "")).strip()
        if len(task_text) > 48:
            task_text = task_text[:47] + "…"
        items.append({
            "text": run_id,
            "display": run_id,
            "description": f"{status} — {task_text}" if task_text else status,
            "kind": "run",
            "replace_start": -len(token),
        })
    return items


def _complete_usage(
    args_region: str,
    subcommands: list[tuple[str, str]],
) -> list[dict[str, Any]]:
    """`/usage <subcmd>` (declared) + `/usage show <mode>` (second level)."""
    completed, token = _split_args(args_region)

    if not completed:
        return _filter_table(token, subcommands, "subcommand")

    if len(completed) == 1 and completed[0].lower() == "show":
        return _filter_table(token, _USAGE_DISPLAY_MODES, "subcommand")

    return []


def _complete_checkpoint(
    args_region: str,
    subcommands: list[tuple[str, str]],
) -> list[dict[str, Any]]:
    """`/checkpoint <subcmd>` (declared) + `/checkpoint backend <backend>`."""
    completed, token = _split_args(args_region)

    if not completed:
        return _filter_table(token, subcommands, "subcommand")

    if len(completed) == 1 and completed[0].lower() == "backend":
        return _filter_table(token, _CHECKPOINT_BACKENDS, "subcommand")

    return []


def _complete_theme(
    args_region: str,
    subcommands: list[tuple[str, str]],
) -> list[dict[str, Any]]:
    """`/theme <name|list|emoji>` + `/theme emoji <on|off>`.

    The verbs are declared; the theme NAMES are not — they belong to the
    TUI theme registry (`ppxai/tui/themes/`), which this layer cannot
    import, so `_THEME_NAMES` stays here. See the module note above.
    """
    completed, token = _split_args(args_region)

    if not completed:
        # First arg: subcommands ("list"/"emoji") + theme names
        subs = _filter_table(token, subcommands, "subcommand")
        themes = _filter_table(token, _THEME_NAMES, "theme")
        return subs + themes

    if len(completed) == 1 and completed[0].lower() == "emoji":
        return _filter_table(token, _EMOJI_OPTIONS, "subcommand")

    return []


def _complete_model(
    args_region: str,
    current_provider: str | None,
) -> list[dict[str, Any]]:
    """`/model <name>` — dynamic, depends on active provider."""
    if not current_provider:
        return []

    _, token = _split_args(args_region)
    provider_config = get_provider_config(current_provider) or {}
    models = provider_config.get("models", {}) or {}

    table: list[tuple[str, str]] = []
    for model_key, model_info in models.items():
        if not isinstance(model_info, dict):
            continue
        model_id = model_info.get("id", model_key)
        model_name = model_info.get("name", model_id)
        table.append((model_id, model_name))

    # /model completion is substring match (matches Rich's behaviour):
    # typing `/model gpt-4` should surface `gpt-4.1-mini` etc.
    token_lower = token.lower()
    return [
        {
            "text": name,
            "display": name,
            "description": desc,
            "kind": "model",
            "replace_start": -len(token),
        }
        for name, desc in table
        if not token_lower
        or token_lower in name.lower()
        or token_lower in desc.lower()
    ]


def _complete_provider(args_region: str) -> list[dict[str, Any]]:
    """`/provider <name>` — configured provider IDs."""
    _, token = _split_args(args_region)
    token_lower = token.lower()

    table: list[tuple[str, str]] = []
    for provider_id, provider_cfg in PROVIDERS.items():
        if not isinstance(provider_cfg, dict):
            continue
        provider_name = provider_cfg.get("name", provider_id)
        table.append((provider_id, provider_name))

    return [
        {
            "text": pid,
            "display": pid,
            "description": pname,
            "kind": "provider",
            "replace_start": -len(token),
        }
        for pid, pname in table
        if not token_lower
        or token_lower in pid.lower()
        or token_lower in pname.lower()
    ]


# =============================================================================
# Path argument completion
# =============================================================================


def _complete_path(
    partial: str,
    working_dir: str,
    include_files: bool = True,
    include_dirs: bool = True,
    max_entries: int = 200,
) -> list[dict[str, Any]]:
    """Shell-style path completion for command arguments."""
    parent, leaf = _resolve_path_base(partial, working_dir)
    if not parent.exists() or not parent.is_dir():
        return []

    leaf_lower = leaf.lower()
    show_hidden = leaf.startswith(".")

    try:
        entries = sorted(
            parent.iterdir(),
            key=lambda p: (not p.is_dir(), p.name.lower()),
        )
    except (OSError, PermissionError):
        return []

    items: list[dict[str, Any]] = []
    for entry in entries:
        if len(items) >= max_entries:
            break
        name = entry.name
        if not show_hidden and name.startswith("."):
            continue
        if leaf_lower and not name.lower().startswith(leaf_lower):
            continue
        try:
            is_dir = entry.is_dir()
        except OSError:
            continue
        if is_dir and not include_dirs:
            continue
        if not is_dir and not include_files:
            continue

        completion_text = name + ("/" if is_dir else "")
        items.append({
            "text": completion_text,
            "display": completion_text,
            "description": "dir" if is_dir else "file",
            "kind": "dir" if is_dir else "file",
            "replace_start": -len(leaf),
        })

    return items


def _resolve_path_base(partial: str, working_dir: str) -> tuple[Path, str]:
    """Split a user-typed partial path into (parent_dir, leaf_prefix)."""
    if not partial:
        return Path(working_dir), ""

    if partial.startswith("~"):
        expanded = str(Path(partial).expanduser())
    elif os.path.isabs(partial):
        expanded = partial
    else:
        expanded = os.path.join(working_dir, partial)

    if expanded.endswith(("/", os.sep)):
        return Path(expanded), ""

    parent_str, leaf = os.path.split(expanded)
    return Path(parent_str), leaf


def _last_ws_token(text: str) -> tuple[int, str]:
    """Return (start_index, token) for the last whitespace-delimited token."""
    if not text:
        return 0, ""
    idx = len(text)
    while idx > 0 and not text[idx - 1].isspace():
        idx -= 1
    return idx, text[idx:]


# =============================================================================
# @file + @context reference completion
# =============================================================================


def _complete_at_query(
    query: str,
    working_dir: str,
    replace_len: int,
    max_files: int = 100,
) -> list[dict[str, Any]]:
    """Complete @-prefixed references: context providers + file refs.

    Context-provider shortcuts (`@git`, `@tree`, `@clipboard`, `@url`)
    appear first so users see them alongside their own files. They only
    survive filtering if the typed prefix matches the shortcut name —
    so `@al` surfaces `alpha.txt` without polluting the dropdown, while
    an empty `@` surfaces both.
    """
    query_lower = query.lower()
    items: list[dict[str, Any]] = []

    # Context providers (prefix match on the bare name after @)
    context_provider_matched = False
    for name, desc in _CONTEXT_PROVIDERS:
        bare = name[1:]
        if not query_lower or bare.lower().startswith(query_lower):
            items.append({
                "text": name,
                "display": name,
                "description": desc,
                "kind": "context_ref",
                "replace_start": -replace_len,
            })
            if query_lower and bare.lower().startswith(query_lower):
                context_provider_matched = True

    # Fast path: skip filesystem scan when the query exclusively matches
    # a context-provider shortcut (e.g. @gi → @git, @tr → @tree). The
    # rglob("*") is expensive on large repos, network mounts, and
    # monorepos — avoid it when the user clearly isn't looking for files.
    # Only scan when: empty query (show everything), no context match
    # (must be a file query), or the query contains path-like characters
    # (dots, slashes) that suggest a filename, not a shortcut.
    skip_filesystem = (
        context_provider_matched
        and query_lower
        and "." not in query_lower
        and "/" not in query_lower
        and "_" not in query_lower
    )

    # File refs
    root = Path(working_dir)
    files: list[tuple[str, str]] = []

    if not skip_filesystem:
        try:
            for path in root.rglob("*"):
                if len(files) >= max_files * 2:
                    break
                try:
                    if not path.is_file():
                        continue
                    if any(ignored in path.parts for ignored in _IGNORE_DIRS):
                        continue
                    rel_path = str(path.relative_to(root))
                    files.append((path.name, rel_path))
                except (ValueError, OSError):
                    pass
        except (PermissionError, OSError):
            pass

    for filename, filepath in files[:max_files]:
        if not query_lower or query_lower in filename.lower() or query_lower in filepath.lower():
            items.append({
                "text": f"@{filename}",
                "display": filename,
                "description": filepath,
                "kind": "file_ref",
                "replace_start": -replace_len,
            })

    return items


__all__ = ["complete"]
