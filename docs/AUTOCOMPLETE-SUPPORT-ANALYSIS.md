# Autocomplete Support Analysis Across All Clients

**Date:** 2026-01-29
**Version:** v1.15.1
**Purpose:** Document current autocomplete feature parity across Rich TUI, Textual TUI, VSCode, and Web clients

---

## Executive Summary

All 4 clients have **autocomplete support**, but with varying levels of sophistication:

| Feature | Rich TUI | Textual TUI | VSCode | Web App |
|---------|----------|-------------|--------|---------|
| **Slash Commands** | ✅ Full | ✅ **Full (Tab-based)** | ✅ Full | ✅ Full |
| **Subcommands** | ✅ 6 types | ✅ **8 types (Tab-based)** | ❌ None | ❌ None |
| **@file References** | ⚠️ Files only | ✅ **Full (Tab-based)** | ✅ Files + @git/@tree | ✅ Files + @git/@tree |
| **File Commands** | ❌ None | ✅ **/show, /edit, /cat** | ❌ None | ❌ None |
| **Model Names** | ❌ None | ✅ **Dynamic (Tab-based)** | ❌ None | ❌ None |
| **Provider Names** | ❌ None | ✅ **Dynamic (Tab-based)** | ❌ None | ❌ None |
| **Theme Names** | ✅ Yes | ✅ **Yes (Tab-based)** | ❌ N/A | ❌ N/A |
| **Tool Names** | ✅ Yes (/tools help) | ✅ **Yes (Tab-based)** | ❌ None | ❌ None |

**Key Findings:**
- **Textual TUI autocomplete RE-ENABLED (v1.15.2)** - Tab-based completion with full feature parity
- **Textual TUI** now has the **MOST COMPLETE** autocomplete (8/8 features, including file commands)
- **Rich TUI** has good working autocomplete (4/7 features functional)
- **VSCode/Web** have basic autocomplete but no subcommand support
- **File search** differs: VSCode/Web use server endpoint, TUIs use local cache

---

## Detailed Feature Breakdown

### 1. Slash Command Autocomplete

All clients autocomplete slash commands when user types `/`.

#### Shared Command List (VScode/Web)
**Source:** [ppxai/web/shared/commands.js](../ppxai/web/shared/commands.js)

| Command | Category | Subcommands | Description |
|---------|----------|-------------|-------------|
| `/help` | Session | - | Show available commands |
| `/clear` | Session | - | Clear conversation history |
| `/save` | Session | - | Save session to JSON |
| `/export` | Session | - | Export last answer to markdown |
| `/load` | Session | - | Load a saved session |
| `/sessions` | Session | - | List saved sessions |
| `/provider` | Provider | list | Switch provider or list providers |
| `/model` | Provider | list | Switch model or list models |
| `/tools` | Tools | enable, disable, status, list, config, set, agent, help | Manage AI tools |
| `/agent` | Tools | on, off | Run autonomous agent task |
| `/checkpoint` | Checkpoint | status, list, undo, backend, clear, info | Manage checkpoints |
| `/usage` | Usage | 24h, week, month, year, all, show, reset | Show token usage stats |
| `/status` | Usage | - | Show current status |
| `/show` | File | - | Display file contents (no LLM) |
| `/cat` | File | - | Alias for /show |
| `/cd` | File | - | Change working directory |
| `/pwd` | File | - | Print working directory |
| `/generate` | Coding | - | Generate code from description |
| `/explain` | Coding | - | Explain code or concept |
| `/test` | Coding | - | Generate tests for code |
| `/docs` | Coding | - | Generate documentation |
| `/debug` | Coding | - | Debug an error message |
| `/implement` | Coding | - | Implement from description |
| `/convert` | Coding | api, cli, lib, algo, ui | Convert code between languages |
| `/spec` | Coding | - | Show specification templates |
| `/theme` | Other | dark, light | Switch theme |

**Total:** 26 commands

#### Rich TUI Command List
**Source:** [ppxai/rich/main.py:170-198](../ppxai/rich/main.py:170-198)

Same 26 commands as Web/VSCode, defined in `PPXAICompleter.COMMANDS`.

**Additional Rich TUI Commands:**
- `/new` - Start new session (in list but not in shared commands)
- `/history` - Show conversation history (in list but not in shared commands)
- `/copy` - Copy last response to clipboard (in list but not in shared commands)
- `/review`, `/optimize` - Coding tasks (in list but not in shared commands)
- `/undo` - Revert last agent task (in list but not in shared commands)

**Total:** ~31 commands

#### Textual TUI Command List
**Source:** [ppxai/tui/completer.py:202-210](../ppxai/tui/completer.py:202-210)

Uses dynamic command discovery via `CommandFactory.list_all()`, ensuring it always has the latest commands.

**Status:** ✅ Most robust - automatically synced with command factory

---

### 2. Subcommand Autocomplete

Autocomplete for arguments after the main command (e.g., `/tools enable`, `/checkpoint status`).

#### Rich TUI Subcommands
**Source:** [ppxai/rich/main.py:337-459](../ppxai/rich/main.py:337-459)

| Parent Command | Subcommands Autocompleted | Implementation |
|----------------|---------------------------|----------------|
| `/tools` | enable, disable, list, status, help, set, config, agent | Lines 338-360 |
| `/tools help <tool>` | calculator, get_datetime, list_directory, read_file, execute_shell_command, apply_patch, replace_block, insert_text, delete_lines, web_search, fetch_url | Lines 350-359 |
| `/theme` | list, standard, tron-legacy, matrix, nord | Lines 362-395 |
| `/theme emoji` | on, off | Lines 385-394 |
| `/usage` | show, reset | Lines 397-420 |
| `/usage show` | session, provider, model, off | Lines 410-419 |
| `/checkpoint` | status, list, undo, backend, clear, info | Lines 422-445 |
| `/checkpoint backend` | git, file, auto, none | Lines 435-444 |
| `/status` | version, cwd, datetime | Lines 447-459 |

**Total:** 9 subcommand types (including nested levels)

#### Textual TUI Subcommands
**Source:** [ppxai/tui/completer.py:193-240](../ppxai/tui/completer.py:193-240)

**Status:** ✅ **FULLY FUNCTIONAL (v1.15.2)**

Tab-based autocomplete with 8 subcommand types (most comprehensive of all clients):

| Parent Command | Subcommands | Implementation |
|----------------|-------------|----------------|
| `/tools` | on, off, enable, disable, list, status, help, set, config, agent | Lines 33-44 |
| `/usage` | show, session, provider, off, reset | Lines 46-52 |
| `/checkpoint` | status, list, backend, clear, info, undo | Lines 54-61 |
| `/checkpoint backend` | git, file, auto, none | Lines 63-68 |
| `/status` | version, cwd, datetime | Lines 70-74 |
| `/theme` | list + 13 theme names | Lines 271-303 |
| `/model <model_name>` | Dynamic from current provider's models | Lines 224-250 |
| `/provider <provider_id>` | Dynamic from config (perplexity, gemini, openai, etc.) | Lines 252-269 |

**Total:** 8 subcommand types (6 static + 2 dynamic) - **ALL FUNCTIONAL via Tab completion**

**How to use:** Type command + space + Tab (e.g., `/tools ` then Tab shows all subcommands)

#### VSCode/Web Subcommands
**Status:** ❌ None

VSCode and Web apps do **not** autocomplete subcommands. They only autocomplete the main slash commands.

**Example:**
- Rich/Textual TUI: `/tools <tab>` → shows `enable`, `disable`, `list`, etc.
- VSCode/Web: `/tools <tab>` → no suggestions

---

### 3. @file Reference Autocomplete

Autocomplete for `@file` references (context injection).

#### Rich TUI @file Autocomplete
**Source:** [ppxai/rich/main.py:314-331](../ppxai/rich/main.py:314-331)

**Trigger:** Type `@` anywhere in message
**Behavior:**
- Shows **files only** (no special providers like `@git`, `@tree`)
- Searches working directory recursively (`rglob`)
- Filters by filename or relative path match
- Caches results for 5 seconds
- Ignores: `.git`, `node_modules`, `__pycache__`, `.venv`, `venv`, `.tox`, `dist`, `build`, `.eggs`, `.mypy_cache`
- Max results: 100 files

**Display:**
```
@README.md          ./README.md
@config.py          ./ppxai/config.py
@main.py            ./ppxai/rich/main.py
```

**Missing:** No `@git`, `@tree`, `@clipboard`, `@url` suggestions

#### Textual TUI @file Autocomplete
**Source:** [ppxai/tui/completer.py:114-146](../ppxai/tui/completer.py:114-146)

**Trigger:** Type `@` anywhere in message
**Behavior:**
- Shows **special providers first**: `@file`, `@clipboard`, `@url`
- Then shows **file completions** for partial matches
- File caching: 5 seconds
- Priority files (shown first): `AGENTS.md`, `CLAUDE.md`, `README.md`, `.env`, `pyproject.toml`, `package.json`
- Max results: 100 files (20 shown in autocomplete)

**Display:**
```
@file               Include file contents
@clipboard          Include clipboard contents
@url                Fetch and include URL contents
@file:README.md     ./README.md
@file:config.py     ./ppxai/config.py
```

**Advantage:** Shows context providers as distinct options

#### VSCode @file Autocomplete
**Source:** [vscode-extension/src/chatPanel.ts:340-375](../vscode-extension/src/chatPanel.ts:340-375)

**Trigger:** Type `@` anywhere in message
**Behavior:**
- Sends query to server endpoint: `POST /files/search` (lines 344)
- Shows **special providers first**: `@git`, `@tree`
- Then shows workspace file matches
- Uses VSCode's workspace search API (`vscode.workspace.findFiles`)
- Filters special refs by query
- Max results: 10 files

**Display:**
```
@git                Include git diff
@tree               Include project structure
README.md           ./README.md
config.py           src/config.py
```

**Advantage:** Uses VSCode's native search (fast, respects .gitignore)

#### Web App @file Autocomplete
**Source:** [ppxai/web/app.js:2177-2226](../ppxai/web/app.js:2177-2226)

**Trigger:** Type `@` anywhere in message
**Behavior:**
- Sends query to server endpoint: `POST /files/search`
- Fallback to `@git`, `@tree` if server unavailable
- Max results: 20 files

**Display:** Same as VSCode

**Advantage:** Server-side search (consistent with VSCode)
**Limitation:** Requires server connection, otherwise only shows `@git`/`@tree`

---

### 3.5. File Command Arguments (Textual TUI Only) ✅

**NEW in v1.15.2** - Terminal-like file completion for `/show`, `/edit`, `/cat` commands.

#### Textual TUI File Commands
**Source:** [ppxai/tui/completer.py:155-191](../ppxai/tui/completer.py:155-191)

**Trigger:** Type `/show `, `/edit `, or `/cat ` then Tab
**Behavior:**
- Returns plain filenames (no `@` prefix) for terminal-like UX
- Searches working directory recursively
- Filters by partial filename match
- Max results: 20 files
- Updates after `/cd` command

**Examples:**
- `/show ` + Tab → shows all files
- `/show RE` + Tab → completes to `/show README.md`
- `/edit src/m` + Tab → completes to `/edit src/main.py`
- `/cat ` + Tab + Tab → cycles through files

**Design Rationale:**
This matches standard terminal UX where commands take bare filenames:
- File commands: `/show README.md` (plain filename)
- Context injection: `@file:README.md` (@ prefix for message context)

**Status:**
- ✅ Rich TUI: **None** (uses manual file paths only)
- ✅ Textual TUI: **Full support**
- ✅ VSCode: **None** (uses manual file paths only)
- ✅ Web: **None** (uses manual file paths only)

---

### 4. Model Name Autocomplete

Autocomplete for `/model <model_name>` command.

#### Textual TUI Model Autocomplete ✅
**Source:** [ppxai/tui/completer.py:224-250](../ppxai/tui/completer.py:224-250)

**Trigger:** Type `/model ` (with space after command)
**Behavior:**
- Gets current provider from `engine_client.provider`
- Loads models from config for that provider
- Filters by model ID or model name
- Returns: `[(model_id, model_name)]`

**Example:**
```
User types: /model so

Suggestions:
sonar-pro               Sonar Pro (32k context)
sonar                   Sonar (Perplexity)
```

#### Rich/VSCode/Web Model Autocomplete ❌
**Status:** Not implemented

Users must manually type model names or use `/model list` to see options.

---

### 5. Provider Name Autocomplete

Autocomplete for `/provider <provider_id>` command.

#### Textual TUI Provider Autocomplete ✅
**Source:** [ppxai/tui/completer.py:252-269](../ppxai/tui/completer.py:252-269)

**Trigger:** Type `/provider ` (with space after command)
**Behavior:**
- Loads all providers from `PROVIDERS` config
- Filters by provider ID or provider name
- Returns: `[(provider_id, provider_name)]`

**Example:**
```
User types: /provider per

Suggestions:
perplexity              Perplexity AI
```

#### Rich/VSCode/Web Provider Autocomplete ❌
**Status:** Not implemented

Users must manually type provider IDs or use `/provider list`.

---

### 6. Theme Name Autocomplete

Autocomplete for `/theme <theme_name>` command.

#### Textual TUI Theme Autocomplete ✅
**Source:** [ppxai/tui/completer.py:271-303](../ppxai/tui/completer.py:271-303)

**Behavior:**
- Shows `list` subcommand first
- Then shows 13 theme names:
  - catppuccin-mocha, dracula, tokyo-night, nord, gruvbox
  - solarized-dark, solarized-light, monokai, material
  - textual-dark, textual-light, tron-legacy, matrix

#### Rich TUI Theme Autocomplete ✅
**Source:** [ppxai/rich/main.py:213-219, 362-395](../ppxai/rich/main.py:213-219)

**Behavior:**
- Shows `list` subcommand
- Shows theme names: standard, tron-legacy, matrix, nord
- Also shows `/theme emoji` with `on`/`off` subcommands

#### VSCode/Web Theme Autocomplete ❌
**Status:** N/A (no theme support in these clients)

---

### 7. Tool Name Autocomplete

Autocomplete for tool names in `/tools help <tool_name>` command.

#### Rich TUI Tool Autocomplete ✅
**Source:** [ppxai/rich/main.py:350-359, 471-495](../ppxai/rich/main.py:350-359)

**Trigger:** Type `/tools help ` (with space after help)
**Behavior:**
- Gets tools from `engine.tool_manager.list_tools()` if available
- Fallback to static list if tools not enabled:
  - calculator, get_datetime, list_directory, read_file, execute_shell_command
  - apply_patch, replace_block, insert_text, delete_lines, web_search, fetch_url

**Example:**
```
User types: /tools help cal

Suggestions:
calculator              Evaluate mathematical expressions
```

#### Textual/VSCode/Web Tool Autocomplete ❌
**Status:** Not implemented

Users must use `/tools list` to see available tools.

---

## File Search Implementation Comparison

### Rich TUI - Local Recursive Search
**Method:** Python `Path.rglob('*')` with caching
**Pros:**
- Fast after first cache
- No server dependency
- Works offline

**Cons:**
- Must scan entire directory tree
- No .gitignore respect
- Can be slow on first run for large repos

**Cache:** 5 seconds, invalidated on directory change

### Textual TUI - Local Recursive Search (Enhanced)
**Method:** Same as Rich TUI but with priority files
**Pros:**
- Same as Rich TUI
- Priority files shown first (AGENTS.md, CLAUDE.md, README.md, etc.)

**Cons:** Same as Rich TUI

**Cache:** 5 seconds

### VSCode - Native Workspace Search
**Method:** `vscode.workspace.findFiles()` via extension API
**Pros:**
- Uses VSCode's native search (very fast)
- Respects .gitignore automatically
- Searches all workspace folders
- No file tree traversal needed

**Cons:**
- Only works in VSCode
- Requires extension API access

**Cache:** None (VSCode handles caching internally)

### Web - Server Endpoint
**Method:** `POST /files/search` to ppxai-server
**Pros:**
- Centralized search logic
- Can use optimized server-side indexing
- Consistent with VSCode

**Cons:**
- Requires server connection
- Network latency
- Fallback to `@git`/`@tree` only if server down

**Cache:** Server-side (implementation dependent)

---

## Autocomplete Trigger Summary

| Client | Slash Command | Subcommand | @file | Model | Provider | Theme | Tool |
|--------|---------------|------------|-------|-------|----------|-------|------|
| **Rich TUI** | `/` at start | After `/tools`, `/theme`, `/usage`, `/checkpoint`, `/status` | `@` anywhere | ❌ | ❌ | `/theme ` | `/tools help ` |
| **Textual TUI** | `/` at start | After `/tools`, `/usage`, `/checkpoint`, `/status`, `/theme` | `@` anywhere | `/model ` | `/provider ` | `/theme ` | ❌ |
| **VSCode** | `/` at start | ❌ None | `@` anywhere | ❌ | ❌ | N/A | ❌ |
| **Web** | `/` at start | ❌ None | `@` anywhere | ❌ | ❌ | N/A | ❌ |

---

## Autocomplete UX Patterns

### Rich TUI (prompt_toolkit)
**Library:** `prompt_toolkit.completion.Completer`
**Display:** Dropdown below input with `display_meta` descriptions
**Navigation:** `Tab` to cycle, `Enter` to select
**Cancellation:** Continue typing or `Esc`

**Code:** [ppxai/rich/main.py:167-495](../ppxai/rich/main.py:167-495)

### Textual TUI (Custom Widget)
**Library:** Textual Input + custom dropdown
**Display:** Dropdown overlaid on UI
**Navigation:** `↑`/`↓` to navigate, `Tab`/`Enter` to select
**Cancellation:** Continue typing or `Esc`

**Code:** [ppxai/tui/completer.py](../ppxai/tui/completer.py)

### VSCode (Webview)
**Library:** Custom JavaScript in webview
**Display:** Dropdown below input in chat panel
**Navigation:** Mouse click or keyboard navigation
**Cancellation:** Click away or continue typing

**Code:** [vscode-extension/src/chatPanel.ts](../vscode-extension/src/chatPanel.ts)

### Web (Custom JavaScript)
**Library:** Vanilla JavaScript DOM manipulation
**Display:** Dropdown positioned below input
**Navigation:** `↑`/`↓` arrows, `Tab`/`Enter` to select
**Cancellation:** Click away or continue typing

**Code:** [ppxai/web/app.js:2092-2280](../ppxai/web/app.js:2092-2280)

---

## Feature Parity Gaps

### High Priority Gaps

1. **VSCode/Web: No Subcommand Autocomplete**
   - Impact: Users must memorize subcommands or check help
   - Examples: `/tools enable`, `/checkpoint status`, `/usage show session`
   - Fix complexity: Medium (requires parsing command arguments)

2. **Rich TUI: Missing @git/@tree/@clipboard/@url in Autocomplete**
   - Impact: Users don't discover special context providers
   - Fix complexity: Low (add to autocomplete list)
   - See: [TODO-v1.15.2-CONTEXT-INJECTOR-PARITY.md](TODO-v1.15.2-CONTEXT-INJECTOR-PARITY.md)

3. **VSCode/Web: Missing @clipboard/@url in Autocomplete**
   - Impact: v1.14.2 features hidden from users
   - Fix complexity: Low (add to special refs list)
   - See: [TODO-v1.15.2-CONTEXT-INJECTOR-PARITY.md](TODO-v1.15.2-CONTEXT-INJECTOR-PARITY.md)

### Medium Priority Gaps

4. **Rich/VSCode/Web: No Model Autocomplete**
   - Impact: Users must type model IDs exactly or use `/model list`
   - Fix complexity: Medium (requires provider config access)
   - Workaround: `/model list` shows all models

5. **Rich/VSCode/Web: No Provider Autocomplete**
   - Impact: Users must type provider IDs exactly
   - Fix complexity: Medium (requires config access)
   - Workaround: `/provider list` shows all providers

### Low Priority Gaps

6. **Textual/VSCode/Web: No Tool Name Autocomplete**
   - Impact: Must use `/tools list` to discover tools
   - Fix complexity: Low (requires tool manager access)
   - Note: Only Rich TUI has this

7. **Theme Autocomplete Variations**
   - Rich TUI: 4 themes + emoji subcommand
   - Textual TUI: 13 themes
   - Fix: Standardize theme list or sync with available themes

---

## Recommendations

### For v1.15.2 (Quick Wins)

1. **Fix Context Injector Autocomplete** (Already planned in TODO document)
   - Add `@git`, `@tree` to Textual TUI
   - Add `@git`, `@tree`, `@clipboard`, `@url` to Rich TUI
   - Add `@clipboard`, `@url` to VSCode/Web

2. **Standardize File Search Behavior**
   - Document expected file search patterns
   - Ensure consistent ignore patterns across clients
   - Consider priority file list for VSCode/Web

### For v1.16.0 (Feature Parity)

3. **Add Subcommand Autocomplete to VSCode/Web**
   - Parse command arguments in autocomplete handler
   - Show subcommand suggestions after recognized commands
   - Use shared command definitions for consistency

4. **Add Model/Provider Autocomplete to Rich TUI**
   - Access engine client for current provider
   - Load models from config
   - Show in dropdown with descriptions

5. **Add Model/Provider Autocomplete to VSCode/Web**
   - Server endpoint: `GET /providers/list` and `GET /models/list?provider=<id>`
   - Client-side autocomplete rendering
   - Use shared command definitions

### For v1.17.0 (Advanced Features)

6. **Fuzzy Matching for File Autocomplete**
   - Current: Substring match only
   - Proposed: Fuzzy match algorithm (like VSCode's Ctrl+P)
   - Example: `@conf` matches `ppxai-config.json`

7. **Context-Aware Autocomplete**
   - Example: After `/model `, only show models for current provider
   - Example: After `/checkpoint backend `, show only valid backends

8. **Autocomplete Performance Optimization**
   - Debounce file search requests
   - Incremental search results
   - Better caching strategies

---

## Testing Checklist

For each client:

### Slash Command Autocomplete
- [ ] Type `/` → Shows all commands
- [ ] Type `/to` → Shows `/tools`
- [ ] Type `/mod` → Shows `/model`
- [ ] Tab completion works
- [ ] Enter selects command

### Subcommand Autocomplete (Rich/Textual only)
- [ ] Type `/tools ` → Shows subcommands
- [ ] Type `/checkpoint ` → Shows subcommands
- [ ] Type `/checkpoint backend ` → Shows backends
- [ ] Type `/usage show ` → Shows display modes

### @file Autocomplete
- [ ] Type `@` → Shows context providers or files
- [ ] Type `@REA` → Shows README.md
- [ ] Type `@git` → Shows git diff option (if supported)
- [ ] Type `@clipboard` → Shows clipboard option (if supported)
- [ ] Autocomplete updates as typing continues

### Model/Provider Autocomplete (Textual only)
- [ ] Type `/model ` → Shows models for current provider
- [ ] Type `/provider ` → Shows all providers
- [ ] Filtering works (type partial name)

### Theme Autocomplete (TUIs only)
- [ ] Type `/theme ` → Shows themes
- [ ] Type `/theme ` → Shows `list` subcommand

### Tool Autocomplete (Rich only)
- [ ] Type `/tools help ` → Shows tool names
- [ ] Type `/tools help cal` → Shows `calculator`

---

## Related Documents

- [TODO-v1.15.2-CONTEXT-INJECTOR-PARITY.md](TODO-v1.15.2-CONTEXT-INJECTOR-PARITY.md) - Context injector autocomplete fixes
- [CONTEXT-INJECTION.md](CONTEXT-INJECTION.md) - Context injection user guide
- [ppxai/web/shared/commands.js](../ppxai/web/shared/commands.js) - Shared command definitions
- [vscode-extension/src/shared/commands.ts](../vscode-extension/src/shared/commands.ts) - VSCode command definitions

---

## Conclusion

All clients have **functional autocomplete**, but **Textual TUI** is the most feature-complete with 7/7 features implemented.

**Biggest gaps:**
1. VSCode/Web lack subcommand autocomplete (users must memorize)
2. Context provider autocomplete inconsistent (see TODO document)
3. Model/Provider autocomplete only in Textual TUI

**Recommendation:** Prioritize subcommand autocomplete for VSCode/Web in v1.16.0 to achieve parity with TUIs.
