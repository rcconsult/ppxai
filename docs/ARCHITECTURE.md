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
│  POST /chat  GET /stream  GET /files/list  POST /command  …     │
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
├── config.py          # LEAF: No ppxai imports (safe to import anywhere)
├── themes.py          # LEAF: No ppxai imports
├── prompts.py         # LEAF: No ppxai imports
├── utils.py           # LEAF: No ppxai imports
├── common/            # Low-level utilities
│   ├── logger.py      # LEAF: No ppxai imports (enable_all/disable_all v1.15.4)
│   ├── preview.py     # LEAF: Preview utilities (v1.15.4)
│   └── consent.py     # Uses logger only
├── preview_server.py  # Stdlib HTTP preview server (v1.15.4)
├── engine/            # Core business logic
│   ├── types.py       # LEAF: No ppxai imports
│   ├── bootstrap.py   # LEAF: Bootstrap context parsing (v1.14.0)
│   ├── providers/     # Provider implementations
│   ├── tools/         # Tool system
│   │   ├── manager.py # Uses types only
│   │   └── builtin/   # Built-in tools (TYPE_CHECKING pattern)
│   └── client.py      # Facade (uses bootstrap.py)
├── server/            # HTTP server
│   └── http.py        # Uses engine, config
├── commands/          # UI-agnostic command layer (v1.15.0 factory + protocol)
│   ├── protocol.py    # CommandContext protocol (interface)
│   ├── factory.py     # CommandFactory + CommandSpec registry
│   ├── context.py     # Adapters: RichCommandContext, TextualCommandContext
│   ├── results.py     # 17 CommandResult types (v1.15.0)
│   ├── system.py      # /help, /status, /theme
│   ├── provider.py    # /provider, /model
│   ├── agent.py       # /agent (agent loop)
│   └── utility.py     # /context, /debug-log
└── main.py            # Entry point
```

## Import Patterns

### 1. TYPE_CHECKING Pattern (Static Analysis Only)

Used in builtin tools to avoid circular imports with manager.py and client.py.

```python
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..manager import ToolManager
    from ...client import EngineClient

def register_tools(manager: 'ToolManager', engine: 'EngineClient'):
    ...
```

**Why**: Type hints are evaluated lazily (as strings) at runtime, so the imports
inside TYPE_CHECKING block are only needed for static type checkers like mypy.

**Files using this pattern**:
- `ppxai/engine/tools/builtin/*.py` (all builtin tools)
- `ppxai/server/session_manager.py`

### 2. DAG Import Structure

The codebase follows a Directed Acyclic Graph (DAG) for imports:

```
config.py, types.py, logger.py  (leaf modules - no ppxai imports)
           ↓
engine/providers/, engine/tools/manager.py
           ↓
engine/client.py
           ↓
commands/  (protocol, factory, handlers, adapters)
           ↓
rich/, tui/, server/  (client layer)
           ↓
main.py (entry points)
```

**Rule**: Each module only imports from modules "below" it in the hierarchy.
No circular dependencies exist. The `commands/` layer uses `TYPE_CHECKING`
for forward references to client types (CommandHandler, PPXAIDEApp).

### 3. Clean Leaf Modules

Modules that have no ppxai imports and can be imported by anything.

- `ppxai/config.py` - Configuration loading and defaults
- `ppxai/themes.py` - Theme definitions
- `ppxai/prompts.py` - Prompt templates
- `ppxai/utils.py` - Utility functions
- `ppxai/engine/types.py` - Type definitions (Message, Event, etc.)
- `ppxai/engine/bootstrap.py` - Bootstrap context parsing (v1.14.0)
- `ppxai/common/logger.py` - Logging setup

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

### Command Dispatch Flow

Both clients share the same 38 commands via `CommandFactory`. Commands are UI-agnostic
— they receive `CommandContext` (protocol) and return typed `CommandResult` objects.

```
                  ┌──────────────────────┐
                  │   CommandFactory      │  Shared registry
                  │   38 CommandSpec      │  (self-registered at import)
                  └─────────┬────────────┘
                            │ spec.handler(context, args)
              ┌─────────────┴─────────────┐
              │                           │
    ┌─────────┴──────────┐    ┌───────────┴────────────┐
    │  RichCommandContext │    │  PPXAIDEApp             │
    │  (adapter)          │    │  (implements protocol   │
    │  wraps Handler      │    │   directly)             │
    └─────────┬──────────┘    └───────────┬────────────┘
              │                           │
    ┌─────────┴──────────┐    ┌───────────┴────────────┐
    │  RichRenderer       │    │  TextualRenderer        │
    │  .render(result)    │    │  .render(result)        │
    │  static dispatch    │    │  async dispatch         │
    └────────────────────┘    └────────────────────────┘
```

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

**Context adapters** (`commands/context.py`) bridge the gap:
- `RichCommandContext` wraps `CommandHandler` — calls **public methods only**
- `TextualCommandContext` wraps `PPXAIDEApp` — calls **public methods only**
- Each client owns its full-stack logic (engine + UI updates)
- Adapters never access private attributes (`_engine_client`, `_model`, etc.)

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
- ⏳ Context injection (`@file`, `@git`, etc.) (planned)
- ⏳ File operations with undo (planned)
- ⏳ Multi-step tool execution (planned)

**Rule:** Any operation that modifies multiple related pieces of state should use this pattern.

---

## Web App Architecture (v1.16.x)

The web app (`ppxai/web/`) serves as the UI for `ppxai-desktop` and the browser-based client. It communicates with `ppxai/server/http.py` via REST + SSE.

### File Structure

```
ppxai/web/
├── index.html                          # Single-page app shell
├── app.js                              # PpxaiApp root class (~2,100 lines after v1.16.2 refactor)
├── shared/                             # Framework-level modules
│   ├── api-client.js                   # ApiClient — all fetch() calls, timeout, error shape
│   ├── app-state.js                    # AppState — centralised state with listener notifications
│   ├── stream-handler.js               # StreamHandler — SSE buffer, RAF rendering, typed events
│   └── command-dispatcher.js           # CommandDispatcher — slash command routing
│       commands/                       # Per-group command handlers
│       ├── file-commands.js            # /show, /edit, /ls, /tree, /cd, /pwd, /preview
│       ├── session-commands.js         # /save, /load, /sessions, /clear, /export
│       ├── model-commands.js           # /provider, /model, /tools, /agent
│       └── …
├── components/
│   ├── file-tree.js                    # FileTreeComponent — collapsible sidebar (v1.16.2)
│   ├── right-panel-frame.js            # RightPanelFrame — LRU view stack navigator (v1.16.2)
│   └── views/
│       ├── base-view.js                # BaseView ABC — mount/unmount/getState/setState protocol
│       ├── code-editor-view.js         # CodeEditorView — CodeMirror 6, unified view/edit
│       ├── markdown-file-view.js       # MarkdownFileView — rendered / source / edit modes
│       ├── data-file-view.js           # DataFileView — table/tree for CSV/JSON/YAML/TOML/HCL
│       ├── image-file-view.js          # ImageFileView — <img> + click-to-zoom
│       └── pdf-file-view.js            # PdfFileView — <embed> iframe
└── styles/
    ├── main.css                        # Global styles
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
| `/command` | POST | CommandFactory server pattern (unified `/usage`, `/status`, etc.) |
| `/set_working_dir` | POST | Change working directory (REST, no SSE emitted) |
| `/interrupt` | POST | Abort current streaming response |
| `/checkpoint/undo` | POST | Undo last agent operation |

## Cross-Client Autocomplete (v1.17.x)

`ppxai/engine/completion.py` is the **single source of truth** for
autocomplete across all four clients. Rich and Textual call it in-
process; Web and VSCode call it via `POST /complete`. Client completers
are pure glue layers — no client owns any subcommand tables, no client
scans its own buffer to decide completion mode.

```
                  ┌──────────────────────────────────────────┐
                  │  engine/completion.py  ::  complete()    │
                  │  ──────────────────────────────────────  │
                  │  • slash commands (CommandFactory)       │
                  │  • aliases + /quit /exit                 │
                  │  • path args (/attach, /cd, ...)         │
                  │  • subcommands (/tools, /usage, ...)     │
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

After the unification, adding a new subcommand or context provider
is a one-file change in `engine/completion.py`. The web client picks
it up for free (no recompile needed, just a server restart). VSCode
picks it up on the next extension reload. Rich and Textual get it
immediately because they call the engine in-process. Tests live next
to the engine logic in `tests/test_completion_provider.py` (39 tests
covering every source).
