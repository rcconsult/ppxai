"""
CompletionProvider — client-agnostic autocomplete engine.

Extracts the completion logic from Rich TUI's `PPXAICompleter` into a
reusable module that all four clients (Rich, Textual, Web, VSCode) can
consume — either in-process (Rich, Textual) or via the `POST /complete`
server endpoint (Web, VSCode).

Completion sources:

1. **Slash commands** — via `CommandFactory.iter_completion_specs()` (the
   public registry snapshot; see ADR 0007). Dynamic, never drifts, sorted
   alphabetically, hidden commands filtered.

2. **Path arguments** — for commands like `/attach`, `/cd`, `/ls`, `/show`
   etc. Shell-style directory traversal with per-command file/dir filters.

3. **Subcommand completion** — for `/tools`, `/usage`, `/checkpoint`,
   `/status`, `/theme`, `/model`, `/provider`. Covers both the first
   subcommand level (`/tools en` → `enable`) and the second level
   (`/usage show session`, `/theme emoji on`, `/tools help <tool>`).

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
from typing import Any, Dict, List, Optional, Tuple

from ..commands.factory import CommandFactory
from ..config import PROVIDERS, get_provider_config


# Commands that accept path arguments, and what kinds of entries make
# sense to complete for each.
_PATH_ARG_COMMANDS: Dict[str, Dict[str, bool]] = {
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

# Commands the factory doesn't own (special-cased in CommandHandler).
_BUILTIN_SPECIAL_COMMANDS: List[Dict[str, Any]] = [
    {"text": "/quit", "description": "Exit the application", "kind": "command"},
    {"text": "/exit", "description": "Exit the application", "kind": "command"},
    # v1.19.0 agent platform — client-side commands (handled in the web
    # dispatcher / VSCode chatPanel, NOT the CommandFactory). Each entry's
    # `clients` set names the clients that actually implement it, and the
    # completion engine surfaces the entry only to those clients: an
    # unfiltered list taught users to type commands that answered
    # "Unknown command" everywhere else (Item 40 VSCode trial, 2026-07-12).
    # Entries without a `clients` key are universal.
    # /run and /task USED to be listed here, gated to {"web", "vscode"},
    # because the in-process TUIs had no channel to the run registry. T8b
    # (v1.19.1) embedded the runner, so both are now real `CommandFactory`
    # commands — universal, and surfaced from the factory like every other
    # command. Listing them here as well would double-list them AND re-apply
    # a gate that no longer describes reality.
    #
    # Availability is now decided per VERB by a capability rather than per
    # client by a name: launching and resuming need a live event loop, which
    # Textual has and Rich does not yet, while ls/get/cancel/collect are
    # synchronous registry reads that work anywhere. See commands/task.py.
    #
    # Item 40: /v1 bearer management (web command-dispatcher.js + VSCode
    # chatPanel.ts; VSCode additionally has the ppxai.setApiToken
    # command-palette entry for masked paste).
    {"text": "/token", "display": "/token",
     "description": "Manage the /v1 API bearer token (status·set·mint·clear)",
     "kind": "command", "clients": {"web", "vscode"}},
]

# Command name (no slash) → clients that implement it. Derived once from
# the entries above; commands without a `clients` tag never appear here.
_CLIENT_GATES: Dict[str, frozenset] = {
    bi["text"].lstrip("/"): frozenset(bi["clients"])
    for bi in _BUILTIN_SPECIAL_COMMANDS
    if "clients" in bi
}


def _client_allows(name: str, client: Optional[str]) -> bool:
    """True when `client` may see the client-side command `name` (no slash).

    `client=None` (legacy/unknown caller) fails open — the pre-gating
    behaviour — so only callers that declare themselves get filtering.
    """
    gate = _CLIENT_GATES.get(name)
    return gate is None or client is None or client in gate

# Context-provider shortcuts — handled by ContextInjector, not the
# filesystem. They appear in the @ dropdown alongside file refs so
# users discover them without having to remember the list.
_CONTEXT_PROVIDERS: List[Tuple[str, str]] = [
    ("@git",       "Include git diff (staged + unstaged)"),
    ("@tree",      "Include project directory structure"),
    ("@clipboard", "Include clipboard text content"),
    ("@url",       "Fetch and include URL content"),
]

# Subcommand tables — the single source of truth that Rich and Textual
# used to each maintain their own copies of. Web and VSCode get these
# for free now that they come through POST /complete.

_TOOLS_SUBCOMMANDS: List[Tuple[str, str]] = [
    ("on",      "Enable AI tools"),
    ("off",     "Disable AI tools"),
    ("enable",  "Enable AI tools"),
    ("disable", "Disable AI tools"),
    ("list",    "List available tools"),
    ("status",  "Show tools status"),
    ("help",    "Show help for a tool"),
    ("set",     "Configure tool settings"),
    ("config",  "Show tool configuration"),
    ("auto",    "Enable/disable agent (auto) mode"),
]

_USAGE_SUBCOMMANDS: List[Tuple[str, str]] = [
    ("show",     "Show usage statistics"),
    ("session",  "Show session usage"),
    ("provider", "Show provider usage"),
    ("off",      "Hide usage display"),
    ("reset",    "Reset usage counters"),
]

_USAGE_DISPLAY_MODES: List[Tuple[str, str]] = [
    ("session",  "Status line shows session totals"),
    ("provider", "Status line shows current provider totals"),
    ("model",    "Status line shows current model totals"),
    ("off",      "Hide usage from status line"),
]

_CHECKPOINT_SUBCOMMANDS: List[Tuple[str, str]] = [
    ("status",  "Show checkpoint status"),
    ("list",    "List recent checkpoints"),
    ("backend", "Set checkpoint backend"),
    ("clear",   "Clear old snapshots"),
    ("info",    "Show checkpoint details"),
    ("undo",    "Revert last checkpoint"),
]

_CHECKPOINT_BACKENDS: List[Tuple[str, str]] = [
    ("git",  "Use git commits"),
    ("file", "Use file snapshots"),
    ("auto", "Auto-detect best backend"),
    ("none", "Disable checkpoints"),
]

_STATUS_SUBCOMMANDS: List[Tuple[str, str]] = [
    ("version",  "Toggle version display"),
    ("cwd",      "Toggle working directory display"),
    ("datetime", "Toggle date/time display"),
]

_THEME_SUBCOMMANDS: List[Tuple[str, str]] = [
    ("list",  "Show available themes"),
    ("emoji", "Toggle emoji mode (on|off)"),
]

_THEME_NAMES: List[Tuple[str, str]] = [
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

_EMOJI_OPTIONS: List[Tuple[str, str]] = [
    ("on",  "Show original emojis"),
    ("off", "Convert to text symbols"),
]

# /task verbs (v1.19.x tool-capable tier; U2 ADR 0011 direct-launch grammar).
# Mirrors the client dispatchers (web task-controller.js handle(), VSCode
# taskController.ts) — the parity sentinel in
# tests/test_vscode_task_controller.py pins THAT pair; this table lists the
# canonical verbs (aliases `list`/`show`/`open`/`ack` omitted as noise).
# There is no `run` verb: `/task "<desc>" --tools a,b,c` launches directly.
_TASK_SUBCOMMANDS: List[Tuple[str, str]] = [
    ("ls",      "List runs"),
    ("get",     "Open a run pane"),
    ("watch",   "Open + live-tail a run"),
    ("respond", "Answer a run parked in waiting (approve|deny|text)"),
    ("collect", "Collect a held result (📬 → finalized)"),
    ("resume",  "Continue an interrupted/cancelled run"),
    ("cancel",  "Cancel a run"),
    ("help",    "Show /task help"),
]

# Which run statuses make sense as the <id> argument of each /task verb.
# None = any run (inspection verbs work on everything, incl. finalized).
# Aliases (show/open/ack) complete ids too — typed by muscle memory.
_TASK_ID_VERB_STATUSES: Dict[str, Optional[frozenset]] = {
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

_TASK_RESPOND_ANSWERS: List[Tuple[str, str]] = [
    ("approve", "Approve the parked request"),
    ("deny",    "Deny the parked request"),
]

# /run verbs (U3, ADR 0011): the one-off family shares the /task lifecycle
# dispatch but launches with no flags and never parks (respond/resume are
# omitted here as noise — they exist but no-op/refuse for oneshot runs).
_RUN_SUBCOMMANDS: List[Tuple[str, str]] = [
    ("ls",      "List one-off runs"),
    ("get",     "Open a run pane"),
    ("watch",   "Open + live-tail a run"),
    ("collect", "Collect a held result (📬 → finalized)"),
    ("cancel",  "Cancel a run"),
    ("help",    "Show /run help"),
]

_TOKEN_SUBCOMMANDS: List[Tuple[str, str]] = [
    ("status", "Show whether a /v1 bearer token is stored (masked)"),
    ("set",    "Store a token — prompts for the value; never type it inline"),
    ("mint",   "Mint + store a token via the loopback bootstrap (local server)"),
    ("clear",  "Remove the stored token"),
]


def complete(
    buffer: str,
    cursor: int = -1,
    *,
    working_dir: Optional[str] = None,
    current_provider: Optional[str] = None,
    tool_names: Optional[List[Tuple[str, str]]] = None,
    agent_runs: Optional[List[Dict[str, Any]]] = None,
    client: Optional[str] = None,
) -> List[Dict[str, Any]]:
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
        client: Which client is asking — "web", "vscode", "rich",
                "textual". Client-side-only commands (/task, /run,
                /token) are surfaced only to the clients that
                implement them. None (legacy/unknown caller) fails open:
                no filtering.

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
            agent_runs or [], client,
        )

    # Bare command name
    return _complete_commands(text, client)


# =============================================================================
# Command name completion
# =============================================================================


def _complete_commands(
    prefix: str, client: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Complete slash command names from the CommandFactory registry.

    Consumes the public `CommandFactory.iter_completion_specs()` snapshot
    rather than the factory's private `_registry` / `_aliases` (ADR 0007
    seam). Behaviour is unchanged: canonicals and aliases, skipping hidden
    commands, with the alias description annotated.
    """
    items: List[Dict[str, Any]] = []
    prefix_lower = prefix.lower()

    for info in CommandFactory.iter_completion_specs():
        if info.hidden:
            continue
        candidate = f"/{info.name}"
        if not candidate.lower().startswith(prefix_lower):
            continue
        if info.is_alias:
            items.append({
                "text": candidate,
                "display": candidate,
                "description": f"{info.description} (alias for /{info.canonical})",
                "kind": "alias",
                "replace_start": -len(prefix),
            })
        else:
            items.append({
                "text": candidate,
                "display": candidate,
                "description": info.description,
                "kind": "command",
                "replace_start": -len(prefix),
            })

    # Builtins — client-side commands only for clients that implement
    # them. The internal `clients` tag is stripped from the emitted item
    # (it's a set, not part of the JSON schema).
    for bi in _BUILTIN_SPECIAL_COMMANDS:
        if not bi["text"].startswith(prefix_lower):
            continue
        if not _client_allows(bi["text"][1:], client):
            continue
        item = {k: v for k, v in bi.items() if k != "clients"}
        item["replace_start"] = -len(prefix)
        items.append(item)

    items.sort(key=lambda e: e["text"])
    return items


# =============================================================================
# Slash arg dispatch
# =============================================================================


def _complete_slash_args(
    text: str,
    space_idx: int,
    wd: str,
    current_provider: Optional[str],
    tool_names: List[Tuple[str, str]],
    agent_runs: List[Dict[str, Any]],
    client: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Route `/cmd ...` to the right arg completer.

    Resolves aliases (so `/att` completes paths just like `/attach`)
    before dispatching. Unknown commands fall through to an empty list.
    """
    typed_cmd = text[1:space_idx]
    spec = CommandFactory.get(typed_cmd)
    canonical = spec.name if spec else typed_cmd
    args_region = text[space_idx + 1:]

    # Subcommand / dynamic tables first
    if canonical == "tools":
        return _complete_tools(args_region, tool_names)
    if canonical == "usage":
        return _complete_usage(args_region)
    if canonical == "checkpoint":
        return _complete_checkpoint(args_region)
    if canonical == "status":
        return _complete_status(args_region)
    if canonical == "theme":
        return _complete_theme(args_region)
    if canonical == "model":
        return _complete_model(args_region, current_provider)
    if canonical == "provider":
        return _complete_provider(args_region)
    if canonical == "task":
        # Same gate as the name completion: no verb/run-id suggestions
        # for a command this client can't dispatch.
        if not _client_allows("task", client):
            return []
        return _complete_task(args_region, agent_runs)
    if canonical == "run":
        # U3: same machinery, one-off verb table, oneshot-kind ids only.
        if not _client_allows("run", client):
            return []
        return _complete_task(
            args_region, agent_runs,
            table=_RUN_SUBCOMMANDS, kind="oneshot",
        )
    if canonical == "token":
        if not _client_allows("token", client):
            return []
        completed, token = _split_args(args_region)
        if not completed:
            return _filter_table(token, _TOKEN_SUBCOMMANDS, "subcommand")
        return []

    # Path arg commands
    path_opts = _PATH_ARG_COMMANDS.get(canonical)
    if path_opts is not None:
        _, token = _last_ws_token(args_region)
        return _complete_path(
            token, wd,
            include_files=path_opts["include_files"],
            include_dirs=path_opts["include_dirs"],
        )

    return []


# =============================================================================
# Subcommand completion helpers
# =============================================================================


def _split_args(args_region: str) -> Tuple[List[str], str]:
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
    table: List[Tuple[str, str]],
    kind: str,
) -> List[Dict[str, Any]]:
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
    tool_names: List[Tuple[str, str]],
) -> List[Dict[str, Any]]:
    """`/tools <subcmd>` + `/tools help <tool>`."""
    completed, token = _split_args(args_region)

    if not completed:
        return _filter_table(token, _TOOLS_SUBCOMMANDS, "subcommand")

    if len(completed) == 1 and completed[0].lower() == "help":
        return _filter_table(token, tool_names, "tool")

    return []


def _complete_task(
    args_region: str,
    agent_runs: List[Dict[str, Any]],
    *,
    table: Optional[List[Tuple[str, str]]] = None,
    kind: str = "task",
) -> List[Dict[str, Any]]:
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
        return _filter_table(
            token, table if table is not None else _TASK_SUBCOMMANDS,
            "subcommand",
        )

    verb = completed[0].lower()

    # `/task respond <id> <answer>` — the third token is the answer word.
    if verb == "respond" and len(completed) == 2:
        return _filter_table(token, _TASK_RESPOND_ANSWERS, "subcommand")

    if len(completed) != 1 or verb not in _TASK_ID_VERB_STATUSES:
        return []

    statuses = _TASK_ID_VERB_STATUSES[verb]
    token_lower = token.lower()
    items: List[Dict[str, Any]] = []
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


def _complete_usage(args_region: str) -> List[Dict[str, Any]]:
    """`/usage <subcmd>` + `/usage show <mode>`."""
    completed, token = _split_args(args_region)

    if not completed:
        return _filter_table(token, _USAGE_SUBCOMMANDS, "subcommand")

    if len(completed) == 1 and completed[0].lower() == "show":
        return _filter_table(token, _USAGE_DISPLAY_MODES, "subcommand")

    return []


def _complete_checkpoint(args_region: str) -> List[Dict[str, Any]]:
    """`/checkpoint <subcmd>` + `/checkpoint backend <backend>`."""
    completed, token = _split_args(args_region)

    if not completed:
        return _filter_table(token, _CHECKPOINT_SUBCOMMANDS, "subcommand")

    if len(completed) == 1 and completed[0].lower() == "backend":
        return _filter_table(token, _CHECKPOINT_BACKENDS, "subcommand")

    return []


def _complete_status(args_region: str) -> List[Dict[str, Any]]:
    """`/status <subcmd>`."""
    completed, token = _split_args(args_region)
    if not completed:
        return _filter_table(token, _STATUS_SUBCOMMANDS, "subcommand")
    return []


def _complete_theme(args_region: str) -> List[Dict[str, Any]]:
    """`/theme <name|list|emoji>` + `/theme emoji <on|off>`."""
    completed, token = _split_args(args_region)

    if not completed:
        # First arg: subcommands ("list"/"emoji") + theme names
        subs = _filter_table(token, _THEME_SUBCOMMANDS, "subcommand")
        themes = _filter_table(token, _THEME_NAMES, "theme")
        return subs + themes

    if len(completed) == 1 and completed[0].lower() == "emoji":
        return _filter_table(token, _EMOJI_OPTIONS, "subcommand")

    return []


def _complete_model(
    args_region: str,
    current_provider: Optional[str],
) -> List[Dict[str, Any]]:
    """`/model <name>` — dynamic, depends on active provider."""
    if not current_provider:
        return []

    _, token = _split_args(args_region)
    provider_config = get_provider_config(current_provider) or {}
    models = provider_config.get("models", {}) or {}

    table: List[Tuple[str, str]] = []
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


def _complete_provider(args_region: str) -> List[Dict[str, Any]]:
    """`/provider <name>` — configured provider IDs."""
    _, token = _split_args(args_region)
    token_lower = token.lower()

    table: List[Tuple[str, str]] = []
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
) -> List[Dict[str, Any]]:
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

    items: List[Dict[str, Any]] = []
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


def _resolve_path_base(partial: str, working_dir: str) -> Tuple[Path, str]:
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


def _last_ws_token(text: str) -> Tuple[int, str]:
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
) -> List[Dict[str, Any]]:
    """Complete @-prefixed references: context providers + file refs.

    Context-provider shortcuts (`@git`, `@tree`, `@clipboard`, `@url`)
    appear first so users see them alongside their own files. They only
    survive filtering if the typed prefix matches the shortcut name —
    so `@al` surfaces `alpha.txt` without polluting the dropdown, while
    an empty `@` surfaces both.
    """
    query_lower = query.lower()
    items: List[Dict[str, Any]] = []

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
    files: List[Tuple[str, str]] = []

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
