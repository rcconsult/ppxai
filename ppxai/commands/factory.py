"""
Command Factory - Central registry for slash commands.

The factory guarantees that all built-in command modules are imported
(and therefore registered) before any read operation on the registry.
This makes command availability deterministic regardless of import path:
``from .factory import CommandFactory`` and ``from . import CommandFactory``
both yield a fully-populated registry.

v1.13.10: Initial implementation (Command Factory pattern)
v1.17.4:  Eager loading — factory owns its preconditions
"""

import importlib
import logging
import re
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Built-in command modules that self-register when imported.
# The factory imports these eagerly on first read access so the registry
# is fully populated regardless of which module imported CommandFactory.
_BUILTIN_COMMAND_MODULES = (
    "session",
    "provider",
    "system",
    "coding",
    "utility",
    "agent",
    "tools",
    "display",
    "attach",
    "doctor",
    # T8b: /task and /run. Registered here rather than per-client because the
    # capability that decides availability is a live event loop, not which
    # client is running — see commands/task.py.
    "task",
    # ADR 0007 step 1b: /quit and /token — registered specs with no server
    # handler, bound to a named client action instead.
    "client_handled",
)


#: Client ids recognized throughout the command registry — the exact
#: strings `rich/main.py`, `tui/completer.py` and
#: `server/routes/completion.py` ask `CommandFactory.roster()` for before
#: handing the result to `engine.completion.complete()` (the last one
#: forwarding the HTTP request's own `client` field, which carries "web"
#: or "vscode"). ADR 0007 step 1a; they passed the id to `complete()`
#: itself until step 4 made the roster the only channel.
KNOWN_CLIENTS = frozenset({"rich", "textual", "web", "vscode"})

#: The two clients `ServerCommandContext` serves — it fields HTTP requests
#: for BOTH web and VSCode and carries no per-request client id, so a
#: caller that only knows "this is the server" gates on this whole set
#: rather than a single client (see `client_sees` and
#: `commands/system.py::_help_client`).
SERVER_CLIENTS = frozenset({"web", "vscode"})

#: Canonical vocabulary of named client-side actions a `CommandSpec` can
#: bind to via `client_action` (ADR 0007). Deliberately Python, not JS —
#: a JS-side copy would be a second source of truth for the exact thing
#: this record exists to remove; each client bundles its own
#: implementation of a name listed here.
#:
#: `token.manage` and `app.quit` are the PURE client-handled pair (no
#: server `handler`, step 1). The other seven are HYBRID (step 2.5,
#: owner-approved vocabulary 2026-09-20): the spec keeps its `handler`
#: for Rich/Textual, and `client_action` names the JS-side behaviour for
#: the clients in `client_action_clients` — `task.controller` (/task),
#: `run.controller` (/run), `auto.loop` (/auto), `coding.stream`
#: (/generate, /explain, /test, /docs, /debug, /implement — one action,
#: the client receives the command name, mirroring VSCode's
#: `CHAT_SHAPED_TASKS`), `coding.convert` (/convert), `preview.panel`
#: (/preview), `help.augment` (/help).
CLIENT_ACTIONS = frozenset({
    "token.manage",
    "app.quit",
    "task.controller",
    "run.controller",
    "auto.loop",
    "coding.stream",
    "coding.convert",
    "preview.panel",
    "help.augment",
})

#: Fixed replacement for the value of a sensitive subcommand argument
#: (ADR 0007 step 3a-sec). A constant, never derived from the secret — a
#: length-preserving mask would leak the length.
SENSITIVE_MASK = "••••"

#: The echo marker the web client puts in front of a typed line
#: (`showSystemMessage(f"> {input}")`). Tolerated so ONE helper redacts
#: both the raw line and its chat echo.
_ECHO_PREFIX = re.compile(r"^\s*>+\s*")

#: `<lead ws>/<command> <ws> <first argument>`. Deliberately token-based
#: (`\S+`), so it is linear in the input length and cannot backtrack —
#: this runs on every `/client-log` message and every `/complete` buffer.
_SLASH_HEAD = re.compile(r"(\s*)/(\S+)(\s+)(\S+)")


def client_sees(
    clients: frozenset[str] | None,
    client: str | frozenset[str] | None,
) -> bool:
    """True when `client` may see a command gated to `clients`.

    The single definition of the visibility gate, shared by `/help` and
    by `roster()` — which is how it reaches completion since ADR 0007
    step 4: the caller asks for ITS client's roster and hands completion
    the filtered data, so `engine/completion.py` has no gate of its own
    any more (`_client_allows` is gone). `clients=None`
    means universal. `client` accepts three shapes:

    - `None` (a legacy or unknown caller) fails OPEN and sees everything
      — the pre-gating behaviour, preserved deliberately (ADR 0007 plan,
      behaviour 1).
    - `str` — a single known client id (e.g. "rich"): visible iff it is
      a member of `clients`.
    - `frozenset[str]` — a CANDIDATE SET of client ids, for a caller that
      knows the audience is one of several clients but not which one
      (`ServerCommandContext`, which serves both web and VSCode over one
      HTTP surface). Visible iff `clients` intersects the candidate set,
      i.e. the command is visible to at least one candidate. This can
      over-list a command gated to only SOME of the candidates — see
      `commands/system.py::_help_client`.
    """
    if clients is None or client is None:
        return True
    if isinstance(client, frozenset):
        return bool(clients & client)
    return client in clients


@dataclass
class CommandSpec:
    """Specification for a slash command.

    Attributes:
        name: Command name without the slash (e.g., "help", "save")
        description: Short description shown in /help
        handler: Function that handles the command: fn(handler, args: str) -> Any.
            Optional — a spec with no handler must instead declare
            `client_action` (see below); `register()` rejects a spec with
            neither.
        category: Category for grouping in help (e.g., "session", "model", "tools")
        aliases: Alternative names for the command
        usage: Usage string shown in help (e.g., "/save [name]")
        hidden: If True, command is not shown in /help
        subcommands: (name, description) pairs, shown in completion/help.
            Shape deliberately matches the `_*_SUBCOMMANDS: list[tuple[str,
            str]]` tables that used to live in `engine/completion.py`
            (ADR 0007 step 1a); step 4 moved the last seven of them here
            and made completion read this field through `roster()`.
            FIRST level only — a second-level argument (`/usage show
            <mode>`, `/checkpoint backend <name>`) has no place in this
            flat shape and stays in the completion logic.
        clients: Which clients can SEE this command. None means universal.
        client_action: Name from `CLIENT_ACTIONS` naming the client-side
            behaviour this command binds to. None means the command has no
            client-handled behaviour at all.
        client_action_clients: Which clients dispatch to `client_action`
            instead of `handler`. None means "every client that can see
            the command" (see `dispatches_in_client`).
        sensitive_subcommands: Names (a subset of `subcommands`) whose
            ARGUMENT is a secret — `/token set <bearer>` (ADR 0007 step
            3a-sec). Everything after such a subcommand must never be
            logged, echoed, persisted or sent anywhere; the one
            implementation of that rule is `redact_sensitive`, and the
            roster publishes the flag per subcommand so clients derive
            the same behaviour instead of hardcoding "/token"/"set".
            ADDITIVE on purpose: `subcommands` keeps its
            `list[tuple[str, str]]` shape.
    """
    name: str
    description: str
    handler: Callable | None = None
    category: str = "general"
    aliases: list[str] = field(default_factory=list)
    usage: str = ""
    hidden: bool = False
    subcommands: list[tuple[str, str]] = field(default_factory=list)
    clients: frozenset[str] | None = None
    client_action: str | None = None
    client_action_clients: frozenset[str] | None = None
    sensitive_subcommands: frozenset[str] = frozenset()

    @property
    def is_client_handled(self) -> bool:
        """True when the command has no server handler at all.

        Distinct from `dispatches_in_client()`: a hybrid command (e.g.
        `/task`) has both a `handler` (for Rich/Textual) and a
        `client_action` (for web/VSCode) — it is NOT client_handled by
        this property, because a server handler exists. `/token` and
        `/quit` (no `handler`) are.
        """
        return self.handler is None and self.client_action is not None

    def dispatches_in_client(self, client: str | None) -> bool:
        """True if `client` should invoke `client_action` rather than
        `handler` for this command.

        Convention (ADR 0007, decided 2026-09-20):
        - No `client_action` -> False.
        - `client_action_clients` is a set -> `client in` it.
        - `client_action_clients` is None (absent) -> True for every
          client that can see the command (`clients is None or client in
          clients`).
        - `client=None` with an absent set -> True only if the spec has
          no handler (legacy/no-client callers get the client action only
          when there is no server-side alternative).
        """
        if self.client_action is None:
            return False
        if self.client_action_clients is not None:
            return client in self.client_action_clients
        if client is None:
            return self.handler is None
        return self.clients is None or client in self.clients


def dispatch_target(
    spec: CommandSpec,
    client: str | frozenset[str] | None,
) -> str:
    """Where `client` runs this command: ``"client"`` or ``"server"``.

    Extends `CommandSpec.dispatches_in_client` (which understands a
    single client id or None) to the CANDIDATE-SET shape `client_sees`
    also accepts. Rule for a set, decided with ADR 0007 step 2: the
    answer is ``"client"`` only when EVERY candidate dispatches in the
    client. A candidate that still routes to the server `handler` must
    not be told the command never reaches the server — over-reporting
    ``"client"`` would break dispatch, while over-reporting ``"server"``
    only costs a round trip the client-handled refusal answers. An empty
    candidate set names no client to dispatch in, so it is ``"server"``.
    """
    if isinstance(client, frozenset):
        if not client:
            return "server"
        return ("client" if all(spec.dispatches_in_client(c) for c in client)
                else "server")
    return "client" if spec.dispatches_in_client(client) else "server"


@dataclass
class CompletionCommandInfo:
    """Minimal, completion-oriented view of a registered command.

    A deliberately narrow, stable shape decoupled from `CommandSpec` (it
    carries no handler / no internal storage). This is the public seam the
    completion logic consumes instead of reaching into the factory's
    private `_registry` / `_aliases`, and the seed of the
    `CommandRegistryProtocol` planned in ADR 0007 (first-class
    `CompletionService`).
    """
    name: str            # command or alias name, without the leading slash
    description: str     # canonical command's description
    hidden: bool         # canonical command's hidden flag
    is_alias: bool       # True if `name` is an alias
    canonical: str       # canonical command name (== name when not an alias)
    # ADR 0007 step 1a: widened so this snapshot can eventually replace
    # commands.js and the `_*_SUBCOMMANDS` tables. All defaulted so
    # existing call sites (which only ever use the fields above) are
    # unaffected. Populated from the canonical spec — an alias entry
    # inherits its canonical command's values.
    usage: str = ""
    category: str = "general"
    subcommands: list[tuple[str, str]] = field(default_factory=list)
    clients: frozenset[str] | None = None
    client_action: str | None = None
    client_action_clients: frozenset[str] | None = None
    client_handled: bool = False
    # ADR 0007 step 3a-sec: subcommands whose argument is a secret.
    sensitive_subcommands: frozenset[str] = frozenset()


class CommandFactory:
    """Central registry for all commands. Leaf module - no ppxai imports.

    Commands self-register at module import time. The factory provides:
    - Registration of command specs
    - Lookup by name or alias
    - Dispatch to command handlers
    - Listing by category
    - Dynamic reloading of user commands

    Example:
        # In a command module (e.g., session.py)
        from .factory import CommandFactory, CommandSpec

        def handle_save(handler, args: str):
            # Save logic here
            pass

        CommandFactory.register(CommandSpec(
            name="save",
            description="Save current session",
            handler=handle_save,
            category="session",
            aliases=["s"],
            usage="/save [name]"
        ))
    """
    _registry: dict[str, CommandSpec] = {}
    _aliases: dict[str, str] = {}  # alias -> canonical name
    _loaded: bool = False
    #: Monotonic counter bumped by every registry mutation (ADR 0007
    #: step 2). It rides on the `GET /commands` payload so a fetch-once
    #: client can tell a stale roster from a current one without
    #: diffing it — `/reload` re-imports `~/.ppxai/commands/*.py` at
    #: runtime, which is the one thing that changes the roster after
    #: startup. Bumped in the three places the registry actually
    #: changes (`register`, `unregister`, `clear`); every other mutating
    #: path, `reload_user_commands` included, goes through those.
    _roster_version: int = 0

    @classmethod
    def _ensure_loaded(cls) -> None:
        """Import all built-in command modules so the registry is populated.

        Called automatically before any read operation. Idempotent — the
        import cost is paid exactly once per process.
        """
        if cls._loaded:
            return
        cls._loaded = True
        for module_name in _BUILTIN_COMMAND_MODULES:
            try:
                importlib.import_module(f".{module_name}", package="ppxai.commands")
            except Exception as e:
                logger.warning(f"Failed to load command module {module_name}: {e}")

    @classmethod
    def _validate_spec(cls, spec: CommandSpec) -> None:
        """Validate a spec's client-handling schema (ADR 0007 step 1a).

        Raises:
            ValueError: naming the command, for any of:
                - neither `handler` nor `client_action` set
                - `client_action` not a name in `CLIENT_ACTIONS`
                - `client_action_clients` set while `client_action` is None
                - `clients` or `client_action_clients` naming a client id
                  outside `KNOWN_CLIENTS`
                - both `clients` and `client_action_clients` given, and the
                  latter is not a subset of the former
                - `sensitive_subcommands` naming something that is not a
                  declared subcommand (ADR 0007 step 3a-sec) — a typo
                  there silently disables redaction, so it fails loudly
        """
        if spec.handler is None and spec.client_action is None:
            raise ValueError(
                f"Command '{spec.name}' has neither a handler nor a client_action"
            )
        if spec.client_action is not None and spec.client_action not in CLIENT_ACTIONS:
            raise ValueError(
                f"Command '{spec.name}' has unknown client_action "
                f"'{spec.client_action}' (not in CLIENT_ACTIONS)"
            )
        if spec.client_action_clients is not None and spec.client_action is None:
            raise ValueError(
                f"Command '{spec.name}' sets client_action_clients without a client_action"
            )
        if spec.clients is not None:
            unknown = spec.clients - KNOWN_CLIENTS
            if unknown:
                raise ValueError(
                    f"Command '{spec.name}' has unknown clients {sorted(unknown)} "
                    f"(not in KNOWN_CLIENTS)"
                )
        if spec.client_action_clients is not None:
            unknown = spec.client_action_clients - KNOWN_CLIENTS
            if unknown:
                raise ValueError(
                    f"Command '{spec.name}' has unknown client_action_clients "
                    f"{sorted(unknown)} (not in KNOWN_CLIENTS)"
                )
        if (
            spec.clients is not None
            and spec.client_action_clients is not None
            and not spec.client_action_clients.issubset(spec.clients)
        ):
            raise ValueError(
                f"Command '{spec.name}' has client_action_clients that is not "
                f"a subset of clients"
            )
        if spec.sensitive_subcommands:
            declared = {sub for sub, _desc in spec.subcommands}
            unknown = set(spec.sensitive_subcommands) - declared
            if unknown:
                raise ValueError(
                    f"Command '{spec.name}' has sensitive_subcommands "
                    f"{sorted(unknown)} that are not declared subcommands"
                )

    @classmethod
    def register(cls, spec: CommandSpec) -> None:
        """Register a command specification.

        Args:
            spec: CommandSpec to register

        Raises:
            ValueError: If the spec fails schema validation (ADR 0007 step
                1a — see `_validate_spec`), or if command name or alias
                already registered
        """
        cls._validate_spec(spec)

        if spec.name in cls._registry:
            logger.warning(f"Command '{spec.name}' already registered, overwriting")

        cls._registry[spec.name] = spec

        # Register aliases
        for alias in spec.aliases:
            if alias in cls._aliases or alias in cls._registry:
                logger.warning(f"Alias '{alias}' conflicts with existing command/alias")
            cls._aliases[alias] = spec.name

        cls._roster_version += 1

    @classmethod
    def unregister(cls, name: str) -> bool:
        """Unregister a command by name.

        Args:
            name: Command name to unregister

        Returns:
            True if command was found and removed, False otherwise
        """
        if name not in cls._registry:
            return False

        spec = cls._registry[name]
        # Remove aliases
        for alias in spec.aliases:
            cls._aliases.pop(alias, None)
        # Remove command
        del cls._registry[name]
        cls._roster_version += 1
        return True

    @classmethod
    def get(cls, name: str) -> CommandSpec | None:
        """Get command spec by name or alias.

        Args:
            name: Command name or alias (without leading /)

        Returns:
            CommandSpec if found, None otherwise
        """
        cls._ensure_loaded()
        # Check if it's an alias
        canonical = cls._aliases.get(name, name)
        return cls._registry.get(canonical)

    @classmethod
    def dispatch(cls, name: str, handler, args: str = "") -> Any:
        """Dispatch a command by name.

        Args:
            name: Command name or alias (without leading /)
            handler: CommandHandler instance providing context
            args: Command arguments string

        Returns:
            Result from command handler

        Raises:
            ValueError: If command not found, or if it is client-handled
                (no server handler — ADR 0007 step 1b)
        """
        spec = cls.get(name)
        if not spec:
            raise ValueError(f"Unknown command: /{name}")
        if spec.handler is None:
            # Deliberately says nothing about `args`: a client-handled
            # command may carry a secret (/token set <value>).
            raise ValueError(
                f"Command /{name} is client-handled "
                f"(client_action='{spec.client_action}') and has no server handler"
            )
        return spec.handler(handler, args)

    @classmethod
    def call(cls, name: str, handler, args: str = "") -> Any:
        """Call another command (for composition).

        This is an alias for dispatch() but semantically indicates
        command-to-command calls rather than external dispatch.

        Args:
            name: Command name (without /)
            handler: CommandHandler instance
            args: Arguments to pass

        Returns:
            Result from the called command

        Raises:
            ValueError: If command not found
        """
        return cls.dispatch(name, handler, args)

    @classmethod
    def list_all(cls) -> list[str]:
        """List all registered command names.

        Returns:
            List of command names (not aliases)
        """
        cls._ensure_loaded()
        return list(cls._registry.keys())

    @classmethod
    def list_by_category(cls, category: str,
                         client: str | frozenset[str] | None = None
                         ) -> list[CommandSpec]:
        """List commands in a category.

        Args:
            category: Category name
            client: Optional client id, or a candidate set of client ids
                for a caller that knows the audience is one of several
                clients (e.g. `SERVER_CLIENTS`) — commands gated away
                from all of them are omitted. None fails open (see
                `client_sees`).

        Returns:
            List of CommandSpec in the category
        """
        cls._ensure_loaded()
        return [spec for spec in cls._registry.values()
                if spec.category == category and not spec.hidden
                and client_sees(spec.clients, client)]

    @classmethod
    def iter_completion_specs(cls) -> list[CompletionCommandInfo]:
        """Public, completion-oriented snapshot of the registry.

        Returns one entry per canonical command followed by one per alias
        (alias entries carry the canonical command's description + hidden
        flag). This replaces direct reads of the private `_registry` /
        `_aliases` from `engine.completion` — see ADR 0007. Order is
        canonicals-then-aliases; callers that need a stable display order
        should sort by their own key (the completion provider sorts by
        candidate text).
        """
        cls._ensure_loaded()
        infos: list[CompletionCommandInfo] = []
        for name, spec in cls._registry.items():
            infos.append(CompletionCommandInfo(
                name=name,
                description=spec.description,
                hidden=spec.hidden,
                is_alias=False,
                canonical=name,
                usage=spec.usage,
                category=spec.category,
                subcommands=spec.subcommands,
                clients=spec.clients,
                client_action=spec.client_action,
                client_action_clients=spec.client_action_clients,
                client_handled=spec.is_client_handled,
                sensitive_subcommands=spec.sensitive_subcommands,
            ))
        for alias, canonical in cls._aliases.items():
            spec = cls._registry.get(canonical)
            if spec is None:
                continue
            infos.append(CompletionCommandInfo(
                name=alias,
                description=spec.description,
                hidden=spec.hidden,
                is_alias=True,
                canonical=canonical,
                usage=spec.usage,
                category=spec.category,
                subcommands=spec.subcommands,
                clients=spec.clients,
                client_action=spec.client_action,
                client_action_clients=spec.client_action_clients,
                client_handled=spec.is_client_handled,
                sensitive_subcommands=spec.sensitive_subcommands,
            ))
        return infos

    @classmethod
    def roster(cls, client: str | frozenset[str] | None = None) -> dict:
        """JSON-able snapshot of the command roster (ADR 0007 step 2).

        THE one serializer. `GET /commands` returns this verbatim for
        web/VSCode; the in-process clients (Rich, Textual) can call it
        directly, so there is no second shape to keep in sync — the
        whole point of the record.

        Shape::

            {"version": <int>, "commands": [ {...}, ... ]}

        One entry per CANONICAL command, with its aliases as a field
        rather than as standalone entries — restating an alias as its
        own row is exactly the `commands.js` duplication this removes.
        Entries are sorted by name so the payload is diffable and
        cacheable, and nothing callable is ever included: `handler` has
        no representation here.

        Args:
            client: Client id, or a candidate set of client ids, or None
                — the three shapes `client_sees` accepts. Commands the
                audience cannot see are omitted, and `dispatch` is
                computed for that same audience (see `dispatch_target`).

        Returns:
            A plain dict of plain data, ready for `json.dumps`.
        """
        cls._ensure_loaded()
        commands = []
        for name in sorted(cls._registry):
            spec = cls._registry[name]
            if not client_sees(spec.clients, client):
                continue
            commands.append({
                "name": spec.name,
                "aliases": sorted(spec.aliases),
                "description": spec.description,
                "usage": spec.usage,
                "category": spec.category,
                "hidden": spec.hidden,
                "subcommands": [
                    # `sensitive` (ADR 0007 step 3a-sec) is what lets a
                    # client redact `/token set <value>` without knowing
                    # the words "token" or "set" — Python declares, the
                    # client derives.
                    {"name": sub, "description": desc,
                     "sensitive": sub in spec.sensitive_subcommands}
                    for sub, desc in spec.subcommands
                ],
                "clients": sorted(spec.clients) if spec.clients is not None else None,
                "client_action": spec.client_action,
                "client_action_clients": (
                    sorted(spec.client_action_clients)
                    if spec.client_action_clients is not None else None
                ),
                "client_handled": spec.is_client_handled,
                "dispatch": dispatch_target(spec, client),
            })
        return {"version": cls._roster_version, "commands": commands}

    @classmethod
    def names_for_client_action(cls, action: str) -> frozenset[str]:
        """Every typed name — canonical AND aliases — bound to `action`.

        ADR 0007 step 5. The in-process TUIs intercept a couple of
        commands BEFORE the factory lookup, because ending the process
        is not something a handler can do. Those intercepts used to
        spell the names out (`if cmd in ("quit", "q", "exit")`), which
        made them a seventh hand-written roster: `/quit` grew the
        `exit` alias on a spec, and two literals in two client files had
        to be remembered.

        Asking for the ACTION rather than for the name keeps the
        declaration in one place and keeps it honest — `app.quit` is
        what the client implements, and the spec says which typed names
        reach it. Names come back WITHOUT the leading slash, which is
        the form both intercepts compare against.

        Returns an empty frozenset for an action nothing declares; the
        caller is a dispatch path, so it must not raise on a registry
        that has been cleared.
        """
        cls._ensure_loaded()
        names: set[str] = set()
        for spec in cls._registry.values():
            if spec.client_action == action:
                names.add(spec.name)
                names.update(spec.aliases)
        return frozenset(names)

    @classmethod
    def get_categories(cls) -> list[str]:
        """Get all unique category names.

        Returns:
            Sorted list of category names
        """
        cls._ensure_loaded()
        categories = set(spec.category for spec in cls._registry.values()
                        if not spec.hidden)
        return sorted(categories)

    @classmethod
    def clear(cls) -> None:
        """Clear all registrations (for testing)."""
        cls._registry.clear()
        cls._aliases.clear()
        cls._loaded = False
        cls._roster_version += 1

    @classmethod
    def roster_version(cls) -> int:
        """Current roster version (see `_roster_version`)."""
        return cls._roster_version

    @classmethod
    def redact_sensitive(cls, text: str) -> str:
        """Mask the VALUE of a sensitive subcommand in a typed line.

        THE one implementation of the redaction rule (ADR 0007 step
        3a-sec). Pure and side-effect free: it reads the registry and
        returns a string, logs nothing and mutates nothing. Every server
        sink that writes or echoes client-supplied text runs it first,
        and `web/shared/command-roster.js::redact` is its client-side
        twin, driven by the same declaration through the roster's
        per-subcommand `sensitive` flag.

        The rule::

            "/token set abc123"      -> "/token set ••••"
            "> /token set abc123"    -> "> /token set ••••"
            "/TOKEN SET abc123"      -> "/TOKEN SET ••••"
            "/token  set\\tabc 123"   -> "/token  set ••••"
            "/token set"             -> unchanged (no value to hide)
            "/token se"              -> unchanged (not a declared subcommand)
            "/token status x"        -> unchanged (not sensitive)
            "/help me"               -> unchanged (no sensitive subcommands)
            "tell me about /token set x" -> unchanged (not a command line)
            ""                       -> unchanged

        Decisions, made explicitly:

        - **Case-INSENSITIVE** on both the command name and the
          subcommand. Not cosmetic: the web dispatcher lowercases the
          command (`parts[0].toLowerCase()`) and `_handleTokenCommand`
          lowercases the verb, so `/TOKEN SET abc` really does store the
          token — a case-sensitive redactor would let exactly that line
          through. The text KEPT is the original, unaltered.
        - **Whitespace-tolerant.** Any run of whitespace (spaces, tabs)
          separates the tokens, and a leading run is ignored. The kept
          prefix is byte-for-byte the original up to the end of the
          subcommand; only the separator before the mask is normalised
          to one space, so the output is deterministic.
        - **A value is required.** Whitespace-only after the subcommand
          is "no value", so `/token set ` passes through and completion
          of `/token se` -> `set` keeps working.
        - **Never raises.** A non-string returns `""`; nothing else in
          the path can throw, and the one defensive `except` fails
          CLOSED (masks) rather than returning the line.

        Args:
            text: a raw typed line, optionally prefixed by the web
                client's `> ` chat-echo marker.

        Returns:
            `text` unchanged, or `text` truncated after the sensitive
            subcommand with `SENSITIVE_MASK` appended.
        """
        if not isinstance(text, str):
            return ""
        body = _ECHO_PREFIX.sub("", text, count=1)
        lead = len(text) - len(body)
        match = _SLASH_HEAD.match(body)
        if match is None:
            return text
        if not body[match.end(4):].strip():
            return text          # `/token set` — a subcommand, no value
        cut = lead + match.end(4)
        try:
            spec = cls.get(match.group(2).lower())
            if spec is None or not spec.sensitive_subcommands:
                return text
            sensitive = {sub.lower() for sub in spec.sensitive_subcommands}
            if match.group(4).lower() not in sensitive:
                return text
        except Exception:        # pragma: no cover — registry read cannot throw
            # Fail CLOSED: this branch is only reachable for something
            # that already looks like `/<command> <arg> <more>`, so
            # masking is the safe direction.
            logger.warning("redact_sensitive: registry lookup failed; masking")
        return f"{text[:cut]} {SENSITIVE_MASK}"

    @classmethod
    def generate_help(cls, client: str | frozenset[str] | None = None,
                      markdown: bool = False) -> str:
        """Generate help text from registered commands.

        Dynamically builds help output grouped by category.

        Args:
            client: Client id, or a candidate set of client ids
                (e.g. `SERVER_CLIENTS`, for a caller that serves several
                clients over one surface and can't tell them apart), to
                filter by — a command gated away from `client` entirely
                (`CommandSpec.clients`) is omitted. None fails open and
                lists everything (see `client_sees`). Declared since
                v1.13.10 but only wired up in ADR 0007 step 1b, when
                `/token` became a registered, web/VSCode-only spec.
            markdown: If True, output GitHub-flavored markdown (web,
                VSCode). If False, Rich console markup (TUI).
                Same content, two formatters.

        Returns:
            Formatted help text
        """
        cls._ensure_loaded()
        if markdown:
            lines = ["**Available Commands:**\n"]
        else:
            lines = ["[bold]Available Commands:[/bold]\n"]

        # Group by category
        for category in cls.get_categories():
            commands = cls.list_by_category(category, client=client)
            if not commands:
                continue

            # Category header
            if markdown:
                lines.append(f"**{category.title()}:**")
            else:
                lines.append(f"[cyan]{category.title()}:[/cyan]")

            # Commands in category, sorted by name
            for cmd in sorted(commands, key=lambda c: c.name):
                alias_str = ""
                if cmd.aliases:
                    if markdown:
                        alias_str = f" *(/{', /'.join(cmd.aliases)})*"
                    else:
                        alias_str = f" [dim](/{', /'.join(cmd.aliases)})[/dim]"
                if markdown:
                    lines.append(f"- `/{cmd.name}`{alias_str} — {cmd.description}")
                else:
                    lines.append(f"  /{cmd.name}{alias_str} - {cmd.description}")

            lines.append("")  # Blank line between categories

        if markdown:
            lines.append("*Use `/help <command>` for detailed help on a specific command.*")
        else:
            lines.append("[dim]Use /help <command> for detailed help on a specific command.[/dim]")
        return "\n".join(lines)

    @classmethod
    def get_command_help(cls, name: str, markdown: bool = False,
                         client: str | frozenset[str] | None = None
                         ) -> str | None:
        """Get detailed help for a specific command.

        Args:
            name: Command name or alias (without leading /)
            markdown: If True, output GitHub-flavored markdown.
                If False, Rich console markup.
            client: Optional client id, or a candidate set of client ids
                (see `client_sees`) — a command gated away from all of
                `client` reads as not found, matching what completion
                and the `/help` listing show it (ADR 0007 step 1b).

        Returns:
            Formatted help text, or None if command not found
        """
        cls._ensure_loaded()
        spec = cls.get(name)
        if not spec:
            return None
        if not client_sees(spec.clients, client):
            return None

        lines = []
        if markdown:
            lines.append(f"### `/{spec.name}` — {spec.description}")
            lines.append("")
            usage = spec.usage if spec.usage else f"/{spec.name}"
            lines.append(f"**Usage:** `{usage}`")
            if spec.aliases:
                aliases = ", ".join(f"`/{a}`" for a in spec.aliases)
                lines.append(f"**Aliases:** {aliases}")
            lines.append(f"**Category:** {spec.category}")
        else:
            lines.append(f"[bold]/{spec.name}[/bold] - {spec.description}")
            lines.append("")
            if spec.usage:
                lines.append(f"[cyan]Usage:[/cyan] {spec.usage}")
            else:
                lines.append(f"[cyan]Usage:[/cyan] /{spec.name}")
            if spec.aliases:
                aliases = ", ".join(f"/{a}" for a in spec.aliases)
                lines.append(f"[cyan]Aliases:[/cyan] {aliases}")
            lines.append(f"[cyan]Category:[/cyan] {spec.category}")

        # Owner decision (2026-09-21): `/help <cmd>` renders the spec's
        # first-level `subcommands` too — eight specs declare them
        # (`/token`, `/theme`, `/status`, `/checkpoint`, `/tools`,
        # `/usage`, `/task`, `/run`) and neither this method nor
        # `generate_help` (the full listing, deliberately untouched)
        # rendered them before. A spec with no `subcommands` renders
        # EXACTLY as above — no section is appended.
        #
        # `sensitive_subcommands` (ADR 0007 step 3a-sec, e.g. `/token
        # set`) is a NAME-level flag: the subcommand's NAME is not a
        # secret and is listed like any other, only its ARGUMENT VALUE
        # is — and there is no value here to leak (`get_command_help`
        # takes no user-typed argument). The marker below is consistent
        # with the per-subcommand `sensitive` flag `roster()` publishes
        # over `GET /commands` — same declaration, another sink.
        if spec.subcommands:
            lines.append("")
            if markdown:
                lines.append("**Subcommands:**")
                for sub, desc in spec.subcommands:
                    marker = (
                        " _(value handled client-side, never sent to "
                        "the server)_"
                        if sub in spec.sensitive_subcommands else ""
                    )
                    lines.append(f"- `{sub}` — {desc}{marker}")
            else:
                lines.append("[cyan]Subcommands:[/cyan]")
                for sub, desc in spec.subcommands:
                    marker = (
                        " [dim](value handled client-side, never sent "
                        "to the server)[/dim]"
                        if sub in spec.sensitive_subcommands else ""
                    )
                    lines.append(f"  {sub} - {desc}{marker}")

        return "\n".join(lines)

    @classmethod
    def reload_user_commands(cls) -> int:
        """Reload user commands from ~/.ppxai/commands/.

        Unregisters existing user commands (category="custom") and
        re-imports all .py files from the user commands directory.

        Returns:
            Number of modules loaded
        """
        # Unregister existing user commands
        user_cmds = [name for name, spec in cls._registry.items()
                     if spec.category == "custom"]
        for name in user_cmds:
            cls.unregister(name)

        # Re-scan and import user commands
        user_commands_dir = Path.home() / ".ppxai" / "commands"
        if not user_commands_dir.exists():
            return 0

        count = 0
        sys.path.insert(0, str(user_commands_dir))
        try:
            for py_file in user_commands_dir.glob("*.py"):
                if not py_file.name.startswith("_"):
                    module_name = py_file.stem
                    try:
                        # Force reimport if already loaded
                        if module_name in sys.modules:
                            importlib.reload(sys.modules[module_name])
                        else:
                            importlib.import_module(module_name)
                        count += 1
                    except Exception as e:
                        logger.warning(f"Failed to load user command {py_file.name}: {e}")
        finally:
            sys.path.pop(0)

        return count
