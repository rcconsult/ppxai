# ppxai Architecture

This document describes the high-level architecture and import patterns used in the ppxai codebase.

## Full Stack Overview

```
┌─────────────────────────────────────────────────────────────────┐
│  Clients                                                        │
│  ┌────────────┐  ┌────────────────┐  ┌─────────────────────┐   │
│  │ ppxai (TUI)│  │ ppxaide (TUI)  │  │ Web App / VSCode     │   │
│  │ Rich-based │  │ Textual-based  │  │ ppxai-desktop binary │   │
│  └─────┬──────┘  └───────┬────────┘  └────────┬────────────┘   │
│        │  direct          │  direct            │  HTTP/SSE      │
└────────┼──────────────────┼────────────────────┼────────────────┘
         │                  │                    │
         ▼                  ▼                    ▼
┌─────────────────────────────────────────────────────────────────┐
│  ppxai/server/http.py   (FastAPI, REST + SSE)                   │
│  POST /chat (SSE)  GET /files/list  POST /command/<name>  …     │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│  ppxai/engine/client.py   (EngineClient facade)                 │
│  restore_session()  chat()  chat_with_tools()  set_provider()   │
└────────────────────────────┬────────────────────────────────────┘
                             │
              ┌──────────────┼──────────────┐
              ▼              ▼              ▼
      providers/       tools/          session/
      BaseProvider    manager.py      session.py
      GeminiProvider  builtin/        checkpoint
      OpenAIProvider  validator.py
      PerplexityProv
```

## Python Module Hierarchy

```
ppxai/
├── config/            # LEAF pkg: No ppxai imports (safe to import anywhere)
│   ├── loader.py      # Config file discovery + load
│   ├── store.py       # ConfigStore, get_config, reload
│   ├── execution.py   # execution.* axis readers (ADR 0010/0011)
│   ├── tls.py         # LEAF: the ONE outbound-TLS resolver (network.ssl.* + SSL_* env)
│   └── …              # paths, providers, tools, features, prompts, context, defaults
├── constants.py       # LEAF: Enums and constants
├── prompts.py         # LEAF: No ppxai imports
├── common/            # Low-level utilities — every file here is a LEAF
│   ├── logger.py      # No ppxai imports (enable_all/disable_all v1.15.4)
│   ├── preview.py     # Preview utilities (v1.15.4)
│   ├── consent.py     # Uses logger only
│   ├── format.py      # format_tokens / format_usage_badge (v1.18.0 Phase 4 — canonical Python source for the JS/TS mirrors in web/shared and vscode/src/shared)
│   ├── autosave_guard.py  # AutosaveFailureGuard state machine (v1.18.0 Phase 5f — surfaces sustained auto-save failures to the user)
│   ├── atomic_file.py     # atomic_replace with Windows lock-retry (v1.18.0 Phase 5g — extracted from editor.py)
│   ├── docx_to_pdf.py     # convert_docx_to_pdf via LibreOffice headless (v1.18.0 Phase 5g — extracted from server/routes/file_serve.py)
│   ├── async_compat.py    # Asyncio compatibility helpers
│   └── file_type.py       # File-type / mimetype helpers
├── preview_server.py  # Stdlib HTTP preview server (v1.15.4)
├── engine/            # Core business logic (~36 modules; the layering-relevant ones shown)
│   ├── types.py       # LEAF: No ppxai imports — ToolManagerProtocol / ToolEngineProtocol live here
│   ├── task_runner.py # build_task_runner — embeddable, drives in-process runs (T8b)
│   ├── task_backend.py# In-process run lifecycle for the TUIs (no HTTP)
│   ├── task_authorizer.py # authorize_task(): THE admission boundary for every tier
│   ├── bootstrap.py   # LEAF: Bootstrap context parsing (v1.14.0)
│   ├── providers/     # Provider implementations
│   ├── tools/         # Tool system
│   │   ├── manager.py # Uses types only
│   │   └── builtin/   # Built-in tools (Protocol-based imports)
│   └── client.py      # Facade (uses bootstrap.py)
├── server/            # HTTP server
│   └── http.py        # Uses engine, config
├── commands/          # UI-agnostic command layer (v1.15.0 factory + protocol)
│   ├── protocol.py    # CommandContext protocol (interface)
│   ├── factory.py     # CommandFactory + CommandSpec registry
│   ├── context.py     # Adapters: RichCommandContext (Pattern A proxy), ServerCommandContext (Pattern B explicit). Textual uses no adapter — see ADR 0002.
│   ├── task.py        # /task + /run handlers; per-verb loop gating (T8b)
│   ├── results.py     # 21 CommandResult types
│   ├── system.py      # /help, /status, /theme
│   ├── provider.py    # /provider, /model
│   ├── agent.py       # /auto (agent loop)
│   └── utility.py     # /context, /debug-log
└── rich/main.py       # Rich TUI entry point (see pyproject [project.scripts])
```

## Import Patterns

### 1. Protocol-Based Dependency Inversion

Circular imports between builtin tools and `manager.py`/`client.py` are broken by
depending on a **Protocol declared in a leaf module**, not on the concrete class.
Imports stay at the top of the file and are real at runtime.

```python
# ppxai/engine/tools/builtin/editor.py
from ...types import ToolEngineProtocol, ToolManagerProtocol
from ..base import BaseTool


def register_tools(manager: ToolManagerProtocol, engine: ToolEngineProtocol):
    ...
```

### Config: three top-level axes (ADR 0010)

Configuration is organised by *what a key describes*, not by which code path
happens to read it:

| Axis | Answers | Examples |
|---|---|---|
| `providers.*` | **WHO** answers | base_url, api keys, models, per-provider `web_search` |
| `tools.*` | **WHAT** each tool is, tier-independently | `tools.shell.*`, `tools.web_search.*`, `tools.<tool>.egress`, the agent *loop* knobs (`max_iterations`, `zombie_threshold`) |
| `execution.*` | **WHERE** work runs | `execution.task.*` (tier switch, sandbox, consent, budgets), `execution.run.*`, `execution.profiles`, `execution.egress_ceiling`, `execution.collect`, `execution.default_subagent` |

The point of the split is that the security surface — tier switch, sandbox,
consent, egress ceiling — reads top-to-bottom in one block instead of being
a sub-key of a sub-key of `tools`. `network.*` sits alongside for transport
settings (`network.ssl.*`, `network.allow_outbound`).

ADR 0010 moved six tier keys off `tools.agent.*` as a **clean break with no
dual-read**: a config left at an old path is silently ignored and reverts to
its default, which is why `/doctor` scans the config *file* for stale paths.

**Why**: `ppxai/engine/types.py` is a leaf — it imports nothing from ppxai — so
anything may import it. The tool depends on the *interface* it actually needs
rather than on `EngineClient`, which would close an import cycle. The concrete
class satisfies the Protocol structurally; nothing needs to inherit from it.

**Protocols defined in `ppxai/engine/types.py`**: `ToolEngineProtocol`,
`ToolManagerProtocol`, `EngineClientProtocol`, `ArtifactRef`,
`MarshallableArtifact`.

> **Do not use `if TYPE_CHECKING:` or function-local imports to break cycles.**
> This codebase deliberately does not use either — a cycle that needs hiding is a
> layering bug, and the fix is a Protocol in a leaf module. There are zero
> `TYPE_CHECKING` blocks in `engine/tools/builtin/` or `server/session_manager.py`
> (both of which an earlier revision of this document incorrectly cited as
> examples of the pattern). See
> [patterns/protocol-dependency-inversion.md](patterns/protocol-dependency-inversion.md).

### 2. DAG Import Structure

The codebase follows a Directed Acyclic Graph (DAG) for imports:

```
config/, engine/types.py, common/logger.py  (leaf modules - no ppxai imports)
           ↓
engine/providers/, engine/tools/manager.py
           ↓
engine/client.py
           ↓
commands/  (protocol, factory, handlers, adapters)
           ↓
rich/, tui/, server/  (client layer)
           ↓
entry points (rich/main.py, tui/__init__.py, server/http.py)
```

**Rule**: Each module only imports from modules "below" it in the hierarchy.
No circular dependencies exist. The `commands/` layer types against
`EngineClientProtocol` rather than importing the concrete `EngineClient`.

Entry points are declared in `pyproject.toml`:

| Script | Target |
|--------|--------|
| `ppxai` | `ppxai.rich.main:main` |
| `ppxaide` | `ppxai.tui:main` |
| `ppxai-server` | `ppxai.server.http:run_server` |
| `ppxai-desktop` | `ppxai.server.http:run_desktop` |

### 3. Clean Leaf Modules

Modules that have no ppxai imports and can be imported by anything.

- `ppxai/config/` - Configuration package (`loader`, `store`, `paths`, `providers`,
  `tools`, `execution`, `features`, `prompts`, `context`, `defaults`)
- `ppxai/engine/types.py` - Protocols and shared type definitions
- `ppxai/constants.py` - Enums and constants
- `ppxai/prompts.py` - Prompt templates
- `ppxai/common/logger.py` - Logging
- `ppxai/engine/bootstrap.py` - Bootstrap context parsing (v1.14.0)

Theme definitions live with their client (`ppxai/rich/themes.py`,
`ppxai/tui/themes/themes.py`), and helpers in `ppxai/rich/utils.py` — none of
these is a top-level leaf module.

These form the "bottom" of the import hierarchy.

### 4. Bootstrap Context (v1.14.0)

The bootstrap module provides project-specific AI instructions:

```
ppxai/engine/bootstrap.py
├── BootstrapContext class
│   ├── base_instructions: str      # Content below YAML ---
│   ├── provider_hints: dict        # provider_id → list[str]
│   ├── model_hints: dict           # regex pattern → list[str]
│   ├── get_prompt_for(provider, model) → str
│   └── get_active_hints_for(provider, model) → dict
│
└── Helper functions:
    ├── find_bootstrap_file(directory, aliases) → Path
    ├── get_bootstrap_files_config() → list[str]
    └── is_bootstrap_enabled() → bool
```

**Integration with client.py:**
- `EngineClient._bootstrap_context: BootstrapContext` stores parsed context
- `set_provider()` and `set_model()` trigger prompt rebuild
- `get_active_hints()` returns detailed breakdown for debugging

## Architectural Layers

```
┌─────────────────────────────────────────────────────┐
│                   Client Layer                       │
│  rich/ (ppxai)  │  tui/ (ppxaide)  │  server/ (HTTP) │
├─────────────────────────────────────────────────────┤
│                   Command Layer                      │
│  commands/ (protocol, factory, handlers, adapters)   │
├─────────────────────────────────────────────────────┤
│                   Engine Layer                       │
│     client.py, session.py, providers/, tools/        │
├─────────────────────────────────────────────────────┤
│                   Common Layer                       │
│           config.py, types.py, logger.py             │
└─────────────────────────────────────────────────────┘
```

**Rule**: Lower layers should NOT import from higher layers.

## Runtime Object Diagrams (v1.16.1)

The two TUI clients — **ppxai** (Rich) and **ppxaide** (Textual) — share the same
engine but have fundamentally different runtime architectures.

### ppxai (Rich TUI)

```
main() → CommandHandler [singleton]
  ├── engine_client: EngineClient [singleton]
  │     ├── provider: BaseProvider          (replaced on /provider switch)
  │     ├── tool_manager: ToolManager
  │     │     ├── tools: dict[str, Tool]
  │     │     └── validator: ResponseValidator
  │     ├── session_manager: SessionManager
  │     ├── context_injector: ContextInjector
  │     ├── checkpoint_manager: CheckpointManager
  │     └── bootstrap_context: BootstrapContext
  ├── prompt_session: PromptSession         (prompt_toolkit)
  │     ├── history: InMemoryHistory
  │     └── completer: PPXAICompleter → CommandHandler (back-ref)
  ├── provider: str          ─┐
  ├── current_model: str      │ public attributes
  ├── auto_route: bool        │ (read by RichCommandContext)
  ├── tools_available: bool   │
  └── tools_verbose: bool    ─┘

  [Per-command dispatch]
  handle_command(user_input)
    → RichCommandContext(self)     [ephemeral, created per call]
        → spec.handler(context, args) → CommandResult
        → RichRenderer.render(result) [static, type-dispatch registry]
```

### ppxaide (Textual TUI)

```
main() → PPXAIDEApp [singleton, IS its own CommandContext]
  ├── _event_bus: EventBus                  (blinker signals)
  ├── _engine_client: EngineClient [singleton]  ← same structure as Rich
  ├── _provider: str           ─┐
  ├── _model: str               │ private state
  ├── _auto_route: bool         │ (exposed via public properties/methods)
  ├── _tools_verbose: bool     ─┘
  │
  ├── Widget tree (from compose()):
  │     ├── Header
  │     ├── StatusBar → BadgeTransaction    (transactional updates)
  │     ├── Horizontal split:
  │     │     ├── FileTree                  (DirectoryTree extension, toggleable)
  │     │     ├── Vertical:
  │     │     │     ├── ChatView → MessageBox[] → Markdown/Static/Button
  │     │     │     └── InputBox → ChatTextArea
  │     │     └── SidePanel → CodeEditor | Markdown | DataViewer
  │     │                       | TreeViewer | ImageViewer
  │     ├── Footer
  │     └── FooterStatus                    (timer-driven)
  │
  └── [Per-command dispatch]
      _handle_command(user_input)
        → spec.handler(self, args) → CommandResult  [self IS the context]
        → TextualRenderer(self).render(result)      [async, per-instance dispatch]
```

### Key Architectural Differences

| Aspect | ppxai (Rich) | ppxaide (Textual) |
|--------|-------------|-------------------|
| Context | `RichCommandContext(handler)` adapter | `PPXAIDEApp` directly (implements protocol) |
| Renderer | `RichRenderer.render()` — static | `TextualRenderer(app).render()` — async, per-instance |
| UI updates | Direct `console.print()` | EventBus signals → widget subscribers |
| State | Public attributes on CommandHandler | Private attrs + public property/method API |
| Widget tree | None (prompt_toolkit only) | Full Textual `compose()` tree |

### Command Dispatch Flow (v1.18.1)

All four clients share the same `CommandFactory`. Commands are
UI-agnostic — they receive a `CommandContext` and return typed
`CommandResult` objects with optional `side_effects[]`. The two
TUIs call the factory in-process; web and VSCode call it over
HTTP via `POST /command/<name>`, which wraps the result in a v1
envelope.

The READ half of the same resource is `GET /commands` (ADR 0007 step
2): `CommandFactory.roster(client)` is the one serializer for the
command roster, so web/VSCode fetch what commands exist instead of
restating them in a hand-written JS catalog. Its `version` moves only
when the registry does, and `/reload` — the only thing that changes the
roster at runtime — emits a `refresh_command_roster` side effect
carrying that version.

**Web consumes it (ADR 0007 step 3a).** `web/shared/command-roster.js`
fetches `GET /commands?client=web` once at startup, refetches on the
`refresh_command_roster` signal, and `CommandDispatcher` routes from the
roster's per-command `dispatch` field rather than a hardcoded `if`-chain;
`web/shared/commands.js` is deleted. With NO roster the dispatcher fails
closed — it refuses slash commands instead of forwarding the ones it
cannot classify, because a forwarded `/token set <value>` would put a
secret in a request body and in the debug log.

**VSCode consumes it the same way (ADR 0007 step 3b).**
`vscode-extension/src/commandRoster.ts` fetches
`GET /commands?client=vscode` as soon as the backend is reachable,
drops the roster when the connection goes away, and refetches on the
`refresh_command_roster` signal;
`vscode-extension/src/commandRouter.ts` routes from the roster's
`dispatch` field, with a `client_action` → implementation registry
(`CLIENT_ACTIONS`) in place of `chatPanel.ts`'s twelve hardcoded
intercepts, and the same fail-closed gate. `src/shared/commands.ts` —
the SIXTH roster the record counts — is deleted. Five commands
(`/tools`, `/checkpoint`, `/context`, `/ls`, `/tree`) are still
intercepted without a declared action, as the named, shrinking
`LEGACY_INTERCEPTS` baseline for step 5's parity fence. Both modules are
`vscode`-free by design (the `taskController.ts` idiom), so the
behavioural tests compile and drive the real TypeScript under Node.

> **Update (2026-09-21, commit `beffa197`).** The fifth command,
> `checkpoint`, migrated too, and `LEGACY_INTERCEPTS` — along with
> `LEGACY_HANDLERS`, the router's legacy branch, `handlers/commands.ts`
> and `handlers/types.ts` — is deleted, not merely emptied. `/checkpoint
> clear` now asks first via `prompt_quick_pick` in all four clients
> (`ppxai/commands/agent.py::_checkpoint_clear`), and both TUIs consume
> command `side_effects` for the first time. See
> `docs/plan-adr-0007-completion-service.md` open owner decision 7.

**Completion derives from the same declaration too (ADR 0007 step 4,
2026-09-21).** The seven hand-written `_*_SUBCOMMANDS` tables in
`engine/completion.py` — the LAST of the six hand-written rosters the
record counted — are gone: a command's first-level subcommands are
`CommandSpec.subcommands`, and each of the three `complete()` callers
(`rich/main.py`, `tui/completer.py`, `server/routes/completion.py`)
passes `CommandFactory.roster(<its client>)["commands"]` in. The side
effect is the layer inversion the record was originally filed for:
`ppxai/engine/` now imports nothing from `ppxai.commands`. See
§Cross-Client Autocomplete.

**Secrets ride the same declaration (ADR 0007 step 3a-sec).** A spec may
mark subcommands whose ARGUMENT is a secret
(`CommandSpec.sensitive_subcommands`; `/token set` is the only one
today), and the roster publishes a `sensitive` flag on each subcommand
entry. `CommandFactory.redact_sensitive()` is the one server-side
implementation of the rule, and `CommandRoster.isSensitive/redact()` the
one client-side implementation — so the web client masks the `> <input>`
chat echo, skips `POST /complete` and keeps the line out of its input
history WITHOUT hardcoding `/token` or `set`, and `POST /client-log`,
`POST /complete` and `POST /command/<name>` redact again server-side for
stale assets. **Step 3b closed the VSCode client half**: the webview
echo is masked, `POST /complete` is skipped, and the raw line is purged
from the webview's ↑ history (the host tells it to forget, so the
webview holds no copy of the rule). With no roster the client fails
closed: every slash command's args are treated as secret.

```
                  ┌────────────────────────┐
                  │  CommandFactory         │  Single registry
                  │  N CommandSpec entries  │  (self-registered at import)
                  └─────────────┬──────────┘
                                │ spec.handler(context, args)
                                │
        ┌───────────────────────┼───────────────────────┐
        │ in-process            │            HTTP path  │
        │                       │                       │
  ┌─────┴─────────┐   ┌─────────┴─────────┐   ┌─────────┴─────────┐
  │ Rich /        │   │ Textual /         │   │ Web (app.js)      │
  │ Textual TUI   │   │ ppxaide.py        │   │ VSCode (chatPanel)│
  │               │   │                   │   │ POST /command/X   │
  │ context =     │   │ context =         │   │ context =         │
  │ RichCmdCtx /  │   │ PPXAIDEApp        │   │ ServerCmdCtx      │
  │ TextualCmdCtx │   │                   │   │                   │
  └─────┬─────────┘   └─────────┬─────────┘   └─────────┬─────────┘
        │                       │                       │
        │ result.side_effects   │ result.side_effects   │ envelope:
        │ read directly         │ read directly         │ {ok, result,
        │                       │                       │  side_effects[],
        │                       │                       │  version: 1}
        ▼                       ▼                       ▼
  ┌─────────────┐       ┌─────────────┐         ┌─────────────────┐
  │ RichRenderer│       │ TextualRdr  │         │ Web/VSCode      │
  │             │       │             │         │ side-effect     │
  │ .render(r)  │       │ .render(r)  │         │ dispatcher      │
  │             │       │ → opens     │         │  → kind→native  │
  │ + ad-hoc    │       │ side panel  │         │    API call     │
  │ side-effect │       │ on FileView │         │                 │
  │ handling    │       │ Result etc. │         │ Web: panels     │
  │ (TBD Step 5)│       │             │         │ VSCode: vscode.*│
  └─────────────┘       └─────────────┘         └─────────────────┘
```

**Wire envelope** (`POST /command/<name>` response):

```json
{
  "ok": true,                      // mirrors result.success
  "result": {                      // CommandResult.to_dict()
    "type": "FileViewResult",
    "status": "success",
    "filepath": "/abs/path.py",
    "content": "..."
  },
  "side_effects": [
    {"kind": "open_editor", "filepath": "/abs/path.py", "line": 42}
  ],
  "version": 1
}
```

**Side-effect kinds (v1.18.1; `prompt_text` added 2026-05-03)** — see
`ppxai/commands/results.py::SideEffectKind` for the full taxonomy. All 17
(`refresh_command_roster` added by ADR 0007 step 2), by category:
- File handling: `open_editor`, `open_viewer`, `show_image`,
  `show_pdf`, `reveal_in_explorer`
- Terminals: `open_terminal`, `run_shell`
- Live previews: `open_html_preview`
- Workspace: `refresh_file_tree`, `refresh_command_roster`
- Preferences: `set_theme`
- Clipboard: `copy_to_clipboard`
- Session/engine: `attach_file`
- Interactive: `prompt_quick_pick`, `prompt_text`
- Messages: `notify`
- VSCode escape hatch: `vscode_delegate`

Open enum — clients ignore unknown kinds. Adding a new kind is
non-breaking; `vscode_delegate` lets the engine call any
`vscode.commands.executeCommand(name, ...args)` for VSCode-only
features (e.g. `workbench.action.openGlobalKeybindings`).

**`prompt_quick_pick` resume protocol** — when the engine needs the
user to pick one of N options, it emits `PROMPT_QUICK_PICK` with
`items: [{label, value}]`. The chosen `value` IS the literal next
args. Client re-issues `POST /command/<command_to_resume>` with
`args=<value>`. No server-side continuation state; every POST is
idempotent given the args. Example: `/show @config` finds 3 matches
→ `value` of each is the absolute path → user picks → second POST
takes the direct branch.

### State-Sync Channels (v1.18.1)

Engine state is canonical. Web/VSCode AppState mirrors stay in sync
through multiple channels — same destination (`updateFromPython`),
different triggers:

```
  ENGINE                              CLIENTS (web, VSCode)
  ──────                              ─────────────────────

  state.set("working_dir", x)
       │
       ▼
  ┌───────────────────┐
  │ _event_queue      │
  │  (in-process)     │
  └────────┬──────────┘
           │
   drain triggers:
           │
   ┌───────┼──────────┬─────────────┐
   │       │          │             │
   ▼       ▼          ▼             ▼
  POST   GET     state-mut      (Phase F:
  /chat  /state  REST           persistent
  SSE    (poll)  response       /events SSE,
                 events[]       deferred)
   │       │     piggyback      to v1.18.2
   │       │     (Phase B)
   │       │     planned
   │       │      Step 2
   ▼       ▼
  client SSE      visibility-
  handler         change /
                  reconnect
                  triggers /state
                       │
                       ▼
              _reanchorFromServer()
                       │
                       ▼
              state.updateFromPython(payload)
                       │
                       ▼
              AppState observers fire
                       │
              ┌────────┴────────┐
              ▼                 ▼
            web UI          VSCode webview
          (file tree,      (panel state,
           badges, etc.)    delegate calls)
```

Both clients have `_reanchorFromServer()` as the single entry
point that reads `/state` and writes the AppState mirror. The
heartbeat-reconnect path AND the visibility/focus path both
delegate to it. Future channels (REST piggyback, persistent
SSE) feed the same shape into the same mirror.

Phases A–E shipped in v1.18.1; Phase F (persistent SSE `GET /events`)
is intentionally deferred — escalate only if observation says A–E
are insufficient. Original planning doc archived at
[docs/archive/TODO-v1.18.1-state-sync-determinism.md](archive/TODO-v1.18.1-state-sync-determinism.md).

### DAG Dependency Rule (v1.16.1)

The `commands/` layer is **shared** between both clients. It must NOT import from
or know the internals of either `rich/` or `tui/`.

```
engine/          ← No UI, no commands
  ↑
commands/        ← UI-agnostic: protocol + factory + handlers + adapters
  ↑
rich/            ← Rich TUI client (imports commands/, engine/)
tui/             ← Textual TUI client (imports commands/, engine/)
server/          ← HTTP server (imports commands/, engine/)
```

**Context delivery** (`commands/context.py`) — three patterns by design,
pinned in [ADR 0002](decisions/0002-command-context-three-pattern-split.md):
- `RichCommandContext` wraps `CommandHandler` (Pattern A — `__getattr__`
  proxy; wrapped class implements protocol via public methods)
- `PPXAIDEApp` IS the context (no wrapper — Textual passes `self`
  directly to command handlers)
- `ServerCommandContext` wraps engine via `EngineClientProtocol`
  (Pattern B — explicit delegation; no UI handler to wrap)
- Each client owns its full-stack logic (engine + UI updates)
- Adapters never access private attributes (`_engine_client`, `_model`, etc.)
- The unused `TextualCommandContext` Pattern-A wrapper was removed in
  v1.18.2 — it had been dead code since v1.15.0. See ADR 0002 for
  why a unified-on-Pattern-B refactor was considered and deferred.

## Adding New Modules

When adding a new module:

1. **Determine the layer** - Where does it fit in the hierarchy?
2. **Check for cycles** - Will importing it create a circular dependency?
3. **Use appropriate pattern**:
   - If needed only for type hints → TYPE_CHECKING
   - If needed at runtime but causes cycle → Lazy import
   - If no cycle risk → Regular import

## Testing Import Health

To verify no circular imports exist:

```bash
python -c "import ppxai"
```

If this fails with ImportError, there's a circular dependency.

---

## Critical Architecture Patterns

### Transactional State Management (GitOps-Style)

**Added:** v1.15.0
**Status:** Critical pattern for AI/agent workflows
**Location:** `ppxai/tui/widgets/status_bar.py` (BadgeTransaction)

#### Problem

AI agents perform multi-step operations that must succeed atomically or fail completely. Partial state updates create inconsistent UI, broken sessions, and user confusion.

**Examples of problematic partial updates:**
- Provider switch succeeds, but model update fails → inconsistent state
- 3 files added to context, 4th fails → partial context injection
- Badge updates half-applied → confusing status display

#### Solution: Checkpoint/Commit/Rollback Pattern

```python
class BadgeTransaction:
    """Transaction for atomic badge updates with rollback support.

    GitOps-style API:
    1. Checkpoint current state (automatic on enter)
    2. Stage operations (add, update, remove, hide, show)
    3. Commit changes (atomic - all succeed or all rollback)
    4. Rollback on failure with user-friendly error messages
    """

    def checkpoint(self) -> None:
        """Backup current badge state."""

    def commit(self) -> tuple[bool, Optional[str]]:
        """Apply staged changes atomically.
        Returns: (success, error_message)
        """

    def rollback(self) -> None:
        """Restore badge state from backup."""
```

#### Usage Pattern

```python
# Atomic multi-operation update
with status_bar.transaction() as txn:
    txn.add("tokens", "Tokens", "1234")
    txn.update("provider", "ollama")
    txn.remove("cost")
    success, error = txn.commit()
    if not success:
        notify_user(f"Update failed: {error}")
        # State automatically rolled back
```

#### Key Features

**1. Validation Phase**
All operations validated before any are applied. Prevents partial updates.

**2. Atomic Application**
Either all operations succeed or none do. No inconsistent intermediate states.

**3. Automatic Rollback**
On failure or exception, state restored to checkpoint. System remains consistent.

**4. User-Friendly Errors**
Clear error messages explain what failed and why.

**5. Chainable Operations**
Fluent API: `txn.add(...).update(...).remove(...).commit()`

**6. Exception Safety**
Context manager auto-rollbacks on exceptions via `__exit__`.

#### Where to Apply This Pattern

**Provider/Model Switching:**
```python
with config_transaction() as txn:
    txn.set_provider("ollama")
    txn.set_model("qwen2.5-coder:32b")
    txn.update_tools(enabled=True)
    txn.update_context_limit(32000)
    success, error = txn.commit()
```

**Context Injection:**
```python
with context_transaction() as txn:
    txn.inject_file("src/main.py")
    txn.inject_file("tests/test_main.py")
    txn.inject_git_diff("HEAD~1")
    success, error = txn.commit()
```

**Session State Management:**
```python
with session_transaction() as txn:
    txn.add_message(user_message)
    txn.update_token_count(tokens_used)
    txn.update_cost(cost)
    txn.save_checkpoint()
    success, error = txn.commit()
```

**Multi-Step Tool Calls:**
```python
with tool_transaction() as txn:
    txn.read_file("config.json")
    txn.modify_config("api_key", new_value)
    txn.write_file("config.json")
    txn.git_commit("Update API key")
    success, error = txn.commit()
```

**UI State Synchronization:**
```python
with ui_transaction() as txn:
    txn.update_statusbar("provider", "ollama")
    txn.update_statusbar("model", "llama3:70b")
    txn.show_panel("side-panel")
    txn.update_title("ollama/llama3:70b")
    success, error = txn.commit()
```

#### Benefits for AI Agents

**State Consistency**
No partial updates that leave system in inconsistent state. Agent actions are atomic units.

**Error Recovery**
Automatic rollback on failure. User sees coherent error messages, not broken UI.

**User Trust**
Predictable behavior: operations complete fully or not at all. No "half-done" states.

**Debugging**
Clear transaction boundaries. Error messages identify which operation failed.

**Composability**
Transactions can be nested or chained. Complex workflows built from simple atomic units.

#### Implementation Guidelines

**1. Identify State Boundaries**
What constitutes a consistent state? What operations must happen together?

**2. Design Checkpoint Format**
What state needs backup? How to serialize/deserialize it?

**3. Implement Validation**
Check all operations before applying any. Fail fast with clear errors.

**4. Ensure Idempotent Rollback**
Rollback should work even if partially applied. Test with intentional failures.

**5. Provide Error Context**
Error messages should explain what failed, why, and what was attempted.

#### Testing Transactional Code

```python
def test_successful_transaction():
    """All operations succeed - state updated."""
    with transaction() as txn:
        txn.add("a", "A", "1")
        txn.add("b", "B", "2")
        success, error = txn.commit()
        assert success
        assert error is None

def test_failed_transaction_rollback():
    """One operation fails - all rollback."""
    initial_state = get_state()
    with transaction() as txn:
        txn.add("a", "A", "1")
        txn.add("a", "Duplicate", "2")  # Fails
        success, error = txn.commit()
        assert not success
        assert "already exists" in error
    assert get_state() == initial_state  # Rolled back

def test_exception_safety():
    """Exception during commit - auto rollback."""
    initial_state = get_state()
    try:
        with transaction() as txn:
            txn.add("a", "A", "1")
            raise RuntimeError("Simulated error")
    except RuntimeError:
        pass
    assert get_state() == initial_state  # Rolled back
```

#### Future Applications

This pattern should be applied to:
- ✅ StatusBar badge management (implemented)
- ✅ Session state management — `EngineClient.restore_session()` (v1.16.1)
- ✅ Context injection (`@file`, `@git`, `@tree`, `@clipboard`, `@url`) — `ContextInjector` in [ppxai/engine/context.py](../ppxai/engine/context.py)
- ✅ File operations with undo — checkpoint registration before editor writes (`_register_checkpoint_file` in [ppxai/engine/tools/builtin/editor.py](../ppxai/engine/tools/builtin/editor.py))
- ✅ Multi-step tool execution — the `chat_with_tools` iteration loop + `AGENT_BEAT` emission in [ppxai/engine/chat.py](../ppxai/engine/chat.py)

**Rule:** Any operation that modifies multiple related pieces of state should use this pattern.

---

## Web App Architecture (v1.16.x)

The web app (`ppxai/web/`) serves as the UI for `ppxai-desktop` and the browser-based client. It communicates with `ppxai/server/http.py` via REST + SSE.

### File Structure

```
ppxai/web/
├── index.html                          # Single-page app shell
├── app.js                              # PpxaiApp root class (~4,160 lines as of v1.19.3)
├── shared/                             # Framework-level modules (flat, not per-group folders)
│   ├── api-client.js                   # ApiClient — all fetch() calls, timeout, error shape
│   ├── app-state.js                    # AppState — centralised state with listener notifications
│   ├── stream-handler.js               # StreamHandler — SSE buffer, RAF rendering, typed events
│   ├── command-dispatcher.js           # CommandDispatcher — roster-driven slash command routing
│   ├── command-roster.js               # CommandRoster — cache over GET /commands (ADR 0007 step 3a)
│   ├── formatters.js                   # Shared output/value formatters
│   ├── result-renderer.js              # CommandResult → DOM rendering (incl. CompositeResult)
│   ├── side-effects.js                 # SideEffectKind handlers (prompt_text, etc.)
│   └── index.js                        # Barrel re-exports
├── components/
│   ├── file-tree.js                    # FileTreeComponent — collapsible sidebar (v1.16.2)
│   ├── right-panel-frame.js            # RightPanelFrame — LRU view stack navigator (v1.16.2)
│   ├── table-viewer.js                 # TableViewer — sortable/filterable data grid
│   ├── tree-viewer.js                  # TreeViewer — collapsible structured-data tree
│   └── views/
│       ├── base-view.js                # BaseView ABC — mount/unmount/getState/setState + toolbar helpers
│       ├── code-editor-view.js         # CodeEditorView — CodeMirror 6, unified view/edit
│       ├── markdown-file-view.js       # MarkdownFileView — rendered / source / edit modes
│       ├── data-file-view.js           # DataFileView — table/tree for JSON/YAML/TOML/HCL
│       ├── office-file-view.js         # OfficeFileView — xlsx/pptx/docx/csv (v1.18.7)
│       ├── image-file-view.js          # ImageFileView — <img> + click-to-zoom
│       ├── pdf-file-view.js            # PdfFileView — <embed> iframe
│       └── terminal-view.js            # TerminalView — shell/preview output
└── styles/
    ├── data-viewers.css                # Table/tree viewer styles
    ├── file-tree.css                   # Sidebar styles
    └── right-panel-frame.css           # Frame chrome + view styles
```

### Module Dependency Graph (Web)

```
app-state.js          (no deps — leaf)
api-client.js         (no deps — leaf)
         ↓
stream-handler.js     (uses api-client)
command-dispatcher.js (uses api-client, app-state)
         ↓
base-view.js          (uses api-client, app-state)
         ↓
*-view.js             (extend BaseView)
         ↓
right-panel-frame.js  (uses views, app-state)
file-tree.js          (uses api-client — standalone, no app-state dep)
         ↓
app.js                (PpxaiApp — orchestrates all modules)
```

### Key Patterns

**AppState** — centralised key-value store with per-key listeners. Views access `serverUrl`, `sessionHeaders`, and config via `appState.get(key)`. No direct import of app-level globals.

**RightPanelFrame** — LRU view stack. `push(view)` deduplicates by path, evicts oldest non-pinned view when full (default depth 10). Back/forward navigation with `Cmd+←/→` (macOS) or `Alt+←/→`. `getState()`/`setState()` on views preserve scroll position and editor cursor across nav.

**FileTreeComponent** — standalone (no AppState). Lazy-loads directory contents via `GET /files/list`. `refresh(clearExpanded=true)` collapses all expanded dirs when working directory changes (prevents stale 404 paths). `onDirCd` callback fires for `..`, double-click, and right-click on directories.

**StreamHandler** — wraps the SSE fetch with a proper line buffer and `requestAnimationFrame`-gated rendering. Exposes an async iterator; `handleStreamEvent()` in app.js dispatches on `event.type`.

**Inline image flow** — when `display_file` SSE fires for an image extension: (1) inline `<img>` injected into chat bubble via `/files/image/{path}` endpoint, tracked in `_streamInlineImages`; (2) `stream_end` prepends `_streamInlineImages` to the server's text response to preserve order; (3) `showToolResult` skips the bubble for `display_file` events.

### Server ↔ Web API (key endpoints)

The **`/v1/*` gateway** is a separate, externally-facing surface — see
[api-gateway.md](api-gateway.md) for its stability contract:

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/v1/oneshot` | POST | **Stable since v1.18.3**, byte-identical wire since v1.18.4. Executes as a `kind=oneshot` registry run since v1.19.1 — same response. |
| `/v1/agent/run` | POST | Tool-free background run (`kind=oneshot`) |
| `/v1/agent/task` | POST | Tool-capable sandboxed run; gated by `execution.task.enabled` |
| `/v1/agent/runs`, `/runs/{id}`, `/runs/{id}/events` | GET | Registry listing, meta, SSE event stream |
| `/v1/agent/runs/{id}/{cancel,respond,ack,resume}` | POST | Lifecycle verbs |
| `/v1/tokens` | POST | Bearer minting (loopback bootstrap) |

⚠️ The whole `/v1/agent/*` + `/v1/tokens` surface is **exempt from the v1
stability contract** until sealed; only `/v1/oneshot` is frozen.

Internal endpoints (these keep evolving):

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/chat` | POST | Stream chat; returns SSE events |
| `/complete` | POST | Autocomplete — returns completion items for buffer+cursor |
| `/files/list` | GET | Directory listing (`at_fs_root` flag) |
| `/files/read` | POST | Read file (returns relative path from working dir) |
| `/files/write` | POST | Write file |
| `/files/image/{path}` | GET | Serve image binary for inline display |
| `/files/serve/{file_id}` | GET | Serve uploaded file by content-addressed ID |
| `/files/preview/{file_id}` | GET | Preview rendering (PPTX slides, DOCX→PDF) |
| `/command/{name}` | POST | CommandFactory server pattern (unified `/usage`, `/status`, etc.). Optional `client` body field (`rich`\|`textual`\|`web`\|`vscode`) gates per-client output exactly; absent = the `{web, vscode}` candidate set |
| `/commands` | GET | Command roster snapshot — `{version, commands[]}` from `CommandFactory.roster()`, one entry per canonical command with aliases as a field. Optional `?client=` (400 if unknown); weak `ETag` + `If-None-Match` → 304 (ADR 0007 step 2) |
| `/context/working_dir` | GET | Read the current working directory |
| `/context/working_dir` | POST | Change working directory (REST, no SSE emitted) |
| `/interrupt` | POST | Abort current streaming response |
| `/checkpoint/undo` | POST | Undo last agent operation |

## Cross-Client Autocomplete (v1.17.x)

`ppxai/engine/completion.py` is the **single source of truth** for
autocomplete BEHAVIOUR across all four clients. Rich and Textual call it
in-process; Web and VSCode call it via `POST /complete`. Client
completers are pure glue layers — no client owns any subcommand tables,
no client scans its own buffer to decide completion mode.

**The command DATA comes from the registry, not from here (ADR 0007
step 4, 2026-09-21).** `complete()` takes a required `roster=`
argument: the caller passes
`CommandFactory.roster(<its client>)["commands"]` — plain dicts, already
filtered for that client. So `ppxai/engine/completion.py` **imports
nothing from `ppxai.commands`** (fenced at zero by
`tests/test_no_new_lazy_imports.py::TestEngineImportsNoCommands`), the
`engine → commands → engine` package cycle is closed, and client gating
is structural: a command the client may not see is simply absent from
the data. Every first-level subcommand is read off
`CommandSpec.subcommands`; with no roster, completion offers no slash
commands while path and `@file` completion still work.

```
                  ┌──────────────────────────────────────────┐
                  │  engine/completion.py  ::  complete()    │
                  │  ──────────────────────────────────────  │
                  │  • slash commands (from roster= data)    │
                  │  • aliases + /quit /exit                 │
                  │  • path args (/attach, /cd, ...)         │
                  │  • subcommands (declared on the spec)    │
                  │  • /model + /provider (dynamic)          │
                  │  • /tools help <tool>                    │
                  │  • @file refs + @git/@tree/@clipboard/   │
                  │    @url context providers                │
                  └──────────────────────────────────────────┘
                         ▲             ▲
            in-process   │             │  in-process
           ┌─────────────┘             └──────────┐
           │                                      │
  ┌────────┴────────┐                  ┌──────────┴────────┐
  │  Rich TUI       │                  │  Textual TUI      │
  │  PPXAICompleter │                  │  TextualCompleter │
  │  (~85 lines)    │                  │  (~100 lines)     │
  └─────────────────┘                  └───────────────────┘

                       POST /complete
           ┌─────────────┐             ┌──────────┐
           │             ▼             ▼          │
  ┌────────┴────────┐                  ┌──────────┴────────┐
  │  server/routes/ │                  │                   │
  │  completion.py  │◀────── ▲ ────────┤  vscode webview   │
  │  passes:        │        │         │  media/main.js    │
  │   • working_dir │        │         │  unified @+/ flow │
  │   • current_    │        │         └───────────────────┘
  │     provider    │        │
  │   • tool_names  │        │         ┌───────────────────┐
  │     (live)      │◀───────┴────────┤  web app.js       │
  └─────────────────┘                  │  _fetchAutocomplete│
                                       └───────────────────┘
```

### Stable completion item schema

Every client — in-process or over HTTP — consumes the same dict shape:

```python
{
  "text":          str,   # text to insert
  "display":       str,   # what to show in the dropdown
  "description":   str,   # hover/meta text
  "kind":          str,   # command | alias | dir | file | file_ref
                          # | context_ref | subcommand | tool | model
                          # | provider | theme
  "replace_start": int,   # negative offset from cursor:
                          # replace |replace_start| chars with text
}
```

Clients map this to whatever native completion type they need
(`prompt_toolkit.Completion` for Rich, tuples for Textual's InputBox,
DOM elements for Web + VSCode webview). `replace_start` is how every
client knows where to splice the text, so `selectAutocompleteItem`
logic is identical across platforms — no special-casing `@` vs `/`.

### Why this matters

Before v1.17.x, each client kept its own hand-maintained tables of
subcommands, context providers, and path-arg rules. They drifted
constantly: Web and VSCode had no `/tools enable` completion; Textual
had `@git`/`@tree`/`@clipboard`/`@url` but Rich didn't; Rich had
`/model` + `/provider` lookups but the others showed nothing. Adding
a new subcommand meant editing five files and guessing which clients
to retest.

After the unification, adding a new subcommand or context provider is a
one-file change. Since ADR 0007 step 4 that file is the COMMAND's own
module, not the engine: a subcommand is a row in its
`CommandSpec(subcommands=[...])`, and completion, `GET /commands` and
every client derive it. (Only completion BEHAVIOUR a flat declaration
cannot express — second-level arguments like `/usage show <mode>`,
and live sources like `/model` ids or `/task` run ids — still lives in
`engine/completion.py`.) The web client picks it up for free (no
recompile needed, just a server restart). VSCode picks it up on the
next extension reload. Rich and Textual get it immediately because
they call the engine in-process. Tests live next to the engine logic
in `tests/test_completion_provider.py`.

## Schema-Driven AppState DTO (v1.17.4)

Every client's observable application state (provider, model, tools,
tokens, context attachments, etc.) derives from **one** JSON schema
file, `ppxai/engine/app_state_schema.json`. This is the golden source
of truth for cross-language state field definitions.

```
    ppxai/engine/app_state_schema.json   ← golden source of truth
              │
    ┌─────────┴─────────────────────────┐
    ▼                                   ▼
Python (engine/app_state.py)       VSCode (appState.ts)
loaded via importlib.resources     loaded via fs.readFileSync from
at module import. AppState.FIELDS  vscode-extension/resources/...
derived from SCHEMA.               (synced by scripts/sync-schema.js
                                   precompile hook, byte-for-byte
                                   equality pinned by pytest)
    │                                   ▲
    │                                   │ sync-schema.js
    │                                   │ (on every npm run compile)
    │                                   │
    │   ┌──────────────────────────────┘
    │   │
    ▼   ▼
GET /schema/app-state   (server/routes/schema.py)
returns canonical SCHEMA as JSON
    │
    ├── Web: server/routes/static.py injects
    │   <script>window.APP_STATE_SCHEMA = {...}</script>
    │   into index.html before shared/app-state.js runs
    │
    └── Diagnostic tooling, CI, future REST consumers
```

### What uses the DTO

| Client | Mechanism | Derivation |
|---|---|---|
| **Python AppState** (Rich TUI + Textual TUI + Engine) | `importlib.resources.files("ppxai.engine") / "app_state_schema.json"` parsed at module import | `AppState.FIELDS` is derived via `_build_fields(SCHEMA)`; mutable defaults cloned per instance |
| **Web AppState** (browser) | `window.APP_STATE_SCHEMA` injected into `index.html` by the FastAPI static route before any script runs | `AppState` constructor reads the global, derives `_pythonToJs` and defaults from `schema.fields` |
| **VSCode AppState** (extension) | `fs.readFileSync()` of `../resources/app-state-schema.json` at module init | `AppState` module-init code builds `PYTHON_TO_TS` + defaults from the loaded JSON |

The Python TUIs (`ppxai` and `ppxaide`) **also** use the schema —
transitively, through the Python `AppState` class in
`ppxai/engine/app_state.py`. They access state via `engine_client.state`
which is a schema-driven `AppState` instance. A
`test_python_tui_state_access_uses_schema_fields_only` test scans the
TUI sources and asserts every `state.get/on/set("<field>")` call
references a schema-declared field — drift surfaces at CI time.

### Schema entry format

```json
{
  "provider": {
    "client": "currentProvider",
    "type": "string",
    "default": "",
    "group": "core",
    "doc": "Active provider ID"
  }
}
```

- **`client`**: camelCase name used by Web (`this.state.currentProvider`)
  and TypeScript (`state.get("currentProvider")`). Python uses the
  snake_case top-level key directly.
- **`type`**: one of `string | boolean | integer | number | array | object`.
- **`default`**: initial value. Mutable defaults (lists, dicts) are
  cloned per instance so observers on one AppState don't leak into
  another.
- **`group`**: documentation/layout hint (`core`, `features`,
  `streaming`, `usage`, `multimodal`, `debug`).
- **`doc`**: optional human-readable description.

### Drift protection

**Updated 2026-09-21 (commit `1953c29c`):** what used to be layer 2
(byte-for-byte DATA copy) now has a TYPE-layer counterpart, and a fifth,
run-time layer was added. Five layers, in increasing severity:

1. **Schema format tests** (`tests/test_app_state.py::TestSchemaDTO`)
   pin that every entry has the required properties, types match
   their defaults, names follow case conventions, etc.
2. **VSCode bundled-copy equality** test does byte-for-byte
   comparison between the canonical JSON and the copy bundled with
   the extension. CI fails if someone edits one without running
   `npm run sync-schema`.
3. **VSCode generated-type equality** (added 2026-09-21).
   `tests/test_app_state_generated_types.py` regenerates
   `vscode-extension/src/appState.generated.ts` in memory from the
   canonical schema and fails on any difference from the tracked file,
   in either direction — the TYPE-layer analogue of layer 2. Before
   this, the TypeScript `AppStateFields` interface was hand-written and
   had silently drifted two fields behind the schema (`lastMessageRole`
   since v1.18.0, `modelSupportsVision` since v1.18.6); no test compared
   the two.
4. **TUI field-name scan** test pins that Rich + Textual source code
   only accesses state fields declared in the schema.
5. **Runtime drift checks**, split by client:
   - **Web** — `updateFromPython()` in `web/shared/app-state.js` warns
     to the console if the server pushes an unknown field. No
     connect-time check; see the caveat below.
   - **VSCode** (added 2026-09-21) — `vscode-extension/src/schemaGuard.ts`
     fetches `GET /schema/app-state` on every (re)connect and compares
     FIELDS with the bundled schema: identical is silent, extra server
     fields are adopted (stored, never rendered) with one log line, a
     compiled-against field missing or retyped gets one visible
     warning naming the fields and both versions, and a 404/fetch
     failure logs once without blocking — the connect-time case layers
     2–3 cannot cover, since server and extension version
     independently (VSIX vs. pip/PyInstaller). Deliberately the
     opposite posture from the command roster's fail-closed gate:
     `AppState` exists before any server does, so there is nothing to
     withhold. `tests/test_vscode_schema_guard_behavior.py`.

**Update (2026-09-21): web now has a connect-time equivalent too.**
`docs/plan-adr-0007-completion-service.md` §"Open owner decisions" item
9 is DECIDED and built. `_reanchorFromServer()` (`ppxai/web/app.js`)
grew an opt-in `checkSchema` parameter, passed `true` only from the two
RECONNECT-shaped boundaries — heartbeat recovery and
`visibilitychange`→visible — never from first page load (same-process
injected schema) or a plain provider/model switch. When true,
`_checkSchemaDrift()` fetches `GET /schema/app-state` and classifies it
with `ppxai/web/shared/app-state-schema-diff.js::compareSchemas`, a
pure-JS re-implementation of `schemaGuard.ts`'s classifier (web loads
no compiled TypeScript) held to identical verdicts by
`tests/test_schema_diff_cross_language_parity.py` over 10 shared
fixtures. `identical` is silent; `extra-only` adopts
(`AppState.adoptSchema()` — unlike VSCode's add-only `adoptFields`,
this fully re-derives the field map, since web has no compile-time
types to protect) with one `console.info`; `incompatible` adopts and
shows ONE chat notice; a fetch failure logs one `console.warn` and
blocks nothing. Tests: `tests/test_web_schema_drift_behavior.py`,
`tests/test_web_schema_drift_reanchor.py`. Full account:
`docs/patterns/appstate.md` §"Run-time skew (VSCode)".

**Version-history fence (layer 6, added 2026-09-21).** The schema's
`"version"` field is now maintained — MAJOR for a field
removed/renamed/retyped, MINOR for a field added or its `default`
changed, starting at `"1.1"` (`"1.0"` never moved across five earlier
field-adding commits, so it is an unmeasured historical marker, not a
signal). `tests/test_app_state_schema_version.py` enforces it against
an append-only `ppxai/engine/app_state_schema_history.json`, one row
per version with pinned fingerprint hashes so a past row can't be
silently edited. Neither run-time classifier above treats `version` as
the verdict — both decide on FIELDS and report `version` only as
context; a version pre-check ahead of the field diff was deliberately
not added, since it would hide exactly the failure mode this fence
exists to catch (a field change landing with no bump).

### Adding a new field

One edit: add an entry to `ppxai/engine/app_state_schema.json`. Then
bump the sentinel count in
`tests/test_app_state.py::TestSchemaDTO::test_schema_has_fields_dict`.
**No hand-edit to a TypeScript interface is needed** — this section
said otherwise before 2026-09-21 ("until v1.18.x codegen lands, add the
camelCase name to the `AppStateFields` TypeScript interface"); that
interface no longer exists. Everything else propagates automatically:

- Python `AppState.FIELDS` picks it up at next import
- `GET /schema/app-state` returns the updated schema
- `serve_index` injects the updated schema into `index.html`
- Web `AppState` reads it from `window.APP_STATE_SCHEMA`
- `sync-schema.js` copies the new JSON to `vscode-extension/resources/`
  **and regenerates `vscode-extension/src/appState.generated.ts`** on
  the next `npm run compile` (or `npm run sync-schema` directly) —
  commit the regenerated file; `tests/test_app_state_generated_types.py`
  fails CI otherwise
- VSCode `AppState` reads the bundled JSON copy; VSCode code that wants
  to read the new field by name imports the regenerated
  `AppStateFields` type

**Corrected 2026-09-21:** the schema-generator work proposed in
`docs/archive/TODO-appstate-codegen.md` was archived as "superseded /
not pursued" on 2026-07-12, and this section previously repeated that
verdict ("until v1.18.x codegen lands ... it was never pursued"). The
TYPE-generation half of that proposal **was** built, on 2026-09-21,
under ADR 0007 (`vscode-extension/scripts/sync-schema.js` emitting
`src/appState.generated.ts`) — driven by a real drift, not by that
archived TODO being revived. The archived doc's YAML-schema and
runtime-schemas-for-k8s/desktop proposals are unrelated and remain not
pursued.

## Agent Heartbeat Primitives (v1.18.0)

Before v1.18.0 the agent tool loop had no structured progress signal
of its own. Every client scraped `TOOL_CALL` / `TOOL_RESULT` / `ERROR`
events to approximate "is the agent still working?" and the engine
had no way to stop a runaway retry loop short of `max_iterations`.
Three recurring failure modes motivated the primitive:

- **Silent multi-minute loops** where a model kept producing tool
  calls but the UI had no way to show progress without re-deriving
  state per client.
- **"apply_patch fails 10× with hallucinated variations"** sessions
  that burned the full iteration budget before giving up.
- **Cross-client renderer drift** — each client approximated agent
  progress from different event subsets, producing four near-identical
  bugs when the engine changed.

### Emission contract (`ppxai/engine/chat.py`)

`chat_with_tools` owns the heartbeat lifecycle. Every run emits
exactly one `AGENT_RUN_START` on entry and exactly one of
`AGENT_RUN_COMPLETE` / `AGENT_RUN_ERROR` on exit. `AGENT_BEAT` fires
once per tool-iteration after `TOOL_GROUP_END`. `AGENT_ZOMBIE` fires
at most once, on the iteration where the circuit breaker trips, and
is always immediately followed by `AGENT_RUN_ERROR`.

```
stream_start
  → AGENT_RUN_START {model, provider, max_iterations, agent_mode}
  → loop:
       tool_group_start
       tool_call / tool_result | tool_error  (per tool)
       tool_group_end
       AGENT_BEAT {iteration, beat, tool, ok, failures, elapsed_s}
       [if failures ≥ zombie_threshold:]
         AGENT_ZOMBIE {reason, threshold, last_tool, iteration, elapsed_s}
         AGENT_RUN_ERROR {reason: "zombie", ...}
         return
  → AGENT_RUN_COMPLETE {iteration, elapsed_s}   ← both exit paths
    (or AGENT_RUN_ERROR on interrupt / provider error)
```

`AGENT_RUN_COMPLETE` is emitted from **both** exit branches
(successful completion and max-iterations reached), regardless of
`ctx.agent_mode`. The legacy `AGENT_COMPLETE` event remains for
backward compatibility, but every new observer should subscribe to
`AGENT_RUN_COMPLETE` instead — it's mode-agnostic and strictly
paired with `AGENT_RUN_START`.

**2026-09-23:** `/task` audit files (`events.jsonl`) now carry
`turn_degraded` and `turn_end` records mirroring this contract (debt
Item 82, `59702221`) — one `turn_degraded` per tool-guard degradation
and one `turn_end` per engine `AGENT_RUN_COMPLETE`/`AGENT_RUN_ERROR`,
carrying `degraded`/`degradation_reasons` verbatim from the engine. A
run's own `agent_run_complete`/`agent_run_error` records are unaffected
— `turn_end` is a separate per-turn record. A missing `turn_end` for a
turn means its outcome is unknown, not clean.

**2026-09-23, same day:** the contract above had three exceptions until
the "every tool-loop exit ends with a run terminal" fix: the
prompt-based fallback's provider error, the retry-synthesis provider
error, and the tool-interrupt return all ended with no terminal. All
three now yield `AGENT_RUN_ERROR`, and
`tests/test_agent_run_terminal_contract.py` fences it structurally:
every `return` in `chat_with_tools`, and the fall-through at the end
of its body (the max-iterations exit), must be immediately preceded by
`AGENT_RUN_ERROR`/`AGENT_RUN_COMPLETE`, or by a final `STREAM_END` with
the run terminal earlier in the same block (the zombie exit). An
uncaught exception is the only way a turn still ends without one.

### `AgentBeatState` (`ppxai/engine/types.py`)

The dataclass is the single source of truth for the heartbeat
payload shape. Treat it as the wire contract: serialize only via
`as_event_data()`, never hand-roll dicts.

```python
@dataclass
class AgentBeatState:
    iteration: int = 0
    beat_sequence: int = 0
    last_beat_time: float = 0.0
    last_tool: str = ""
    last_run_ok: bool = True
    consecutive_failures: int = 0
    start_time: float = 0.0

    @property
    def elapsed_s(self) -> float: ...
    def as_event_data(self) -> Dict[str, Any]:
        # {iteration, beat, tool, ok, failures, elapsed_s} — all JSON
        # primitives, no datetimes, no enums, stable across releases.
```

### AppState lifecycle

`AppState.agent_beat` (schema default `{}`) is the canonical field
every client renders from. The engine — not clients — owns
invalidation:

- `EngineClient._chat_with_tools` intercepts every `AGENT_BEAT`
  event and calls `self.state.set("agent_beat", event.data)`.
- On `AGENT_RUN_COMPLETE` / `AGENT_RUN_ERROR` (and legacy
  `AGENT_COMPLETE` for defensiveness) it sets `agent_beat = {}`.
- `agent_beat` is in `_SSE_SYNC_FIELDS`, so the server pushes every
  write over `state_sync` SSE with no per-route plumbing.

This follows the v1.17.4 §"Cross-Client State Through AppState"
pattern: clients subscribe (`state.on("agent_beat", listener)`) or
read (`state.get("agent_beat")`); they never scan events themselves.
`AppState.set()` equality-dedupes, so no-op writes don't flood the
SSE stream on text-only turns.

### Zombie circuit-breaker

The breaker reads `tools.agent.zombie_threshold` from
`get_agent_config()` (default `3`, canonical default in
`constants.py::Default.ZOMBIE_THRESHOLD`). `0` disables.

After each iteration's beat is emitted, `_get_zombie_threshold(ctx)`
is consulted; if `consecutive_failures >= threshold` the engine
emits `AGENT_ZOMBIE`, then `AGENT_RUN_ERROR`, and returns
immediately. The loop never reaches the next `max_iterations` check.

`consecutive_failures` is reset on any successful iteration
(`last_run_ok = True`), so transient tool errors don't accumulate
across unrelated turns.

### Renderer contract (per client)

Every renderer reads the same payload and clears on empty dict:

| Client | Surface | Variant cues |
|---|---|---|
| Rich (`TUIEventHandler._tui_agent_beat`) | Dim one-liner after each tool group | Text-only; zombie uses red warning |
| ppxaide (`PPXAIDEApp._on_agent_beat_changed`) | Persistent status-bar badge | `success` / `error` / `warning` variant via failure streak |
| Web (`updateAgentBeatBadge`) | Header badge | `.warn` (≥2 failures) / `.error` (single fail) CSS classes |
| VSCode (`updateAgentBeatBadge` in webview) | Header badge | Same variant logic with `vscode-badge-*` theme tokens |

Adding a new client means: (1) subscribe to the existing AppState
field — do not add new engine events; (2) render the six-key
payload; (3) hide when the dict is empty. No engine changes needed.

### Drift protection

- `tests/test_agent_beat_primitives.py` pins the dataclass defaults,
  `as_event_data()` keys, and EventType membership.
- `tests/test_agent_beat_emission.py` locks the event ordering and
  failure-counter reset semantics in `chat_with_tools`.
- `tests/test_agent_beat_zombie.py` exercises breaker thresholds and
  config round-trips.
- `tests/test_agent_beat_sse.py` runs the full real-engine + real-SSE
  path with a MockProvider so wire format can't drift silently.
- `tests/test_stream_handler_dispatch.py` fails if a new heartbeat
  EventType lands without updating ppxaide's `NOOP_EVENTS` set.


## Error Routing Conventions (v1.18.0)

Errors can reach the user through three different channels. Which
one to pick depends on **who needs to know** and **how quickly**.

### Three channels

1. **Event bus → user-visible** — `emit(Event(EventType.ERROR, ...))`
   or a typed event that the clients render as a toast / bubble.
   Use this when the error is caused by *the current user action*
   and the user needs to act on it (bad input, permission denied,
   provider API error, consent declined).

2. **Logger (warning / error)** — `logger.warning(...)` or
   `logger.error(..., exc_info=True)`.
   Use this when the error is a *system condition* the user can't
   do anything about and shouldn't be interrupted by (retryable
   network blip, non-critical background task failure, cleanup
   operation that failed harmlessly). These land in `server-debug.log`
   when debug logging is enabled.

3. **Raise** — let the exception propagate.
   Use this when the error is *a programming bug* (invariant
   violation, type mismatch, "this should never happen"). Raising
   makes the bug loud during development.

### Decision rules

- **If the user initiated the action, they must see the outcome.**
  Silent failure of a user-initiated action is misleading. Route to
  the event bus even if the error is "just" a log-worthy condition.

- **Background auto-saves, auto-retries, and cleanup operations**
  should log at WARNING when they fail and surface a user-visible
  event only on sustained failure (e.g. 3 consecutive auto-save
  failures mean the disk probably filled up — tell the user, don't
  just keep writing to the log).

- **`except Exception: pass` is almost always wrong** — at minimum
  log what was swallowed. Two narrow exceptions are acceptable:
  - Textual `query_one` guards that catch `NoMatches` specifically
    (the widget might not be mounted; that's expected).
  - Listener isolation in `AppState.set/update` — a misbehaving
    listener can't be allowed to wedge the fan-out, so we catch
    and log at WARNING with traceback.

### What currently violates these rules

Auto-save failure in the Rich TUI and the Textual TUI (see
`rich/main.py`, `tui/stream_handler.py`) log a warning but never
tell the user, so a user whose session save has been failing for
minutes sees "everything looks fine." v1.18.0 Phase 5f adds a
user-visible warning after 3 consecutive auto-save failures and
resets the counter on the first success. See the Phase 5f commit
for the guard mechanism.

### When in doubt

Prefer the event bus. A toast the user can dismiss is strictly
better than a log line they'll never read. Noisy clients lose users
slowly; silently broken clients lose them suddenly.
