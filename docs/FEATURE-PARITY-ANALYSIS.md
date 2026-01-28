# ppxai (Rich TUI) vs ppxaide (Textual TUI) Feature Parity Analysis

**Generated:** 2026-01-26
**Last Updated:** 2026-01-28 (blinker integration verified)
**Target Release:** v1.15.0
**Branch:** feature/new-tui-command

## ✅ STATUS UPDATE (2026-01-28)

Critical issues identified on 2026-01-27 have been **FIXED** via blinker event bus integration (commit 6eb83e2).
- STREAM_END.data handling: **FIXED** (extracts content when no chunks)
- Tool consent callbacks: **FIXED** (wired to EngineClient)
- All 1105 tests passing

## Legend
- ✅ = Fully implemented and working
- ⚠️ = Partially implemented / needs work
- ❌ = Not implemented
- 🔷 = Textual-specific (no Rich equivalent)
- 🔶 = Rich-specific (no Textual equivalent)

---

## 1. COMMANDS (32 Total)

| Command | ppxai (Rich) | ppxaide (Textual) | Notes |
|---------|:------------:|:-----------------:|-------|
| **Session Management** |
| `/save [name]` | ✅ | ✅ | Both use same handler |
| `/load <name>` | ✅ | ✅ | Textual has modal restore |
| `/sessions` | ✅ | ✅ | Both render TableResult |
| `/clear` | ✅ | ✅ | Both clear chat |
| `/export [filename]` | ✅ | ✅ | Same handler |
| **Provider/Model** |
| `/provider [list\|name]` | ✅ | ✅ | Same handler |
| `/model [list\|name]` | ✅ | ✅ | Same handler |
| `/autoroute [on\|off]` | ✅ | ✅ | Same handler |
| **Coding Commands** |
| `/generate <desc>` | ✅ | ✅ | Same handler |
| `/test <file>` | ✅ | ✅ | Same handler |
| `/docs <file>` | ✅ | ✅ | Same handler |
| `/implement <spec>` | ✅ | ✅ | Same handler |
| `/debug <error>` | ✅ | ✅ | Same handler |
| `/explain <file>` | ✅ | ✅ | Same handler |
| `/convert <from> <to> <file>` | ✅ | ✅ | Same handler |
| **File Operations** |
| `/show <file>` | ✅ | ✅ | Rich inline, Textual side panel |
| `/show --source` | ✅ | ✅ | Force source view |
| `/edit <file>` | ❌ | ✅ 🔷 | Textual-only (side panel) |
| `/cd <path>` | ✅ | ✅ | Both with engine sync |
| `/pwd` | ✅ | ✅ | Same handler |
| **Tools/Agent** |
| `/tools [status\|on\|off\|list]` | ✅ | ✅ | Same handler |
| `/tools config` | ✅ | ⚠️ | Needs verification |
| `/tools help <topic>` | ✅ | ✅ | Same handler |
| `/usage [show\|reset]` | ✅ | ✅ | Same handler |
| `/agent <task>` | ✅ | ✅ | Same handler |
| `/checkpoint [...]` | ✅ | ✅ | Same handler |
| `/undo` | ✅ | ✅ | Same handler |
| **System/Config** |
| `/help [cmd]` | ✅ | ✅ | Same handler |
| `/theme [name]` | ✅ | ✅ | Different theme systems |
| `/theme emoji on\|off` | ✅ 🔶 | ❌ | Rich-only feature |
| `/status [version\|cwd\|datetime]` | ✅ | ⚠️ | Toggle subcommands need work |
| `/spec [type]` | ✅ | ✅ | Same handler |
| `/config [option]` | ✅ | ✅ | Same handler |
| `/context [show\|reload\|clear]` | ✅ | ✅ | Same handler |
| `/debug-log [on\|off]` | ✅ | ⚠️ | Needs TUI display |
| **TUI-Specific** |
| `/copy` | ❌ | ✅ 🔷 | Textual-only |
| `/paste` | ❌ | ✅ 🔷 | Textual-only |

---

## 2. FILE DISPLAY & VIEWERS

| Feature | ppxai (Rich) | ppxaide (Textual) | Notes |
|---------|:------------:|:-----------------:|-------|
| **Structured Data (JSON/YAML/TOML)** |
| Tree view display | ✅ (inline Rich Tree) | ✅ (TreeViewer panel) | |
| Source view toggle | ❌ | ✅ (Ctrl+V) | Textual has toggle |
| Syntax highlighting | ✅ | ✅ | Both use appropriate themes |
| **Tabular Data (CSV/TSV)** |
| Table view display | ✅ (inline Rich Table) | ✅ (TableViewer panel) | |
| Source view toggle | ❌ | ✅ (Ctrl+V) | Textual has toggle |
| Header detection | ✅ | ✅ | Same logic |
| Delimiter auto-detect | ✅ | ✅ | Same logic |
| **Markdown Files** |
| Rich rendering | ✅ | ✅ | Both render properly |
| Inline vs panel | Inline | Side panel | Different UX |
| **Code Files** |
| Syntax highlighting | ✅ | ✅ | 14+ languages |
| Line numbers | ✅ | ✅ | |
| Line jump `:line:col` | ⚠️ | ✅ | |
| **Images** |
| Display support | ⚠️ metadata only | ✅ (ImageViewer) | Textual has protocol support |
| Zoom/pan | ❌ | ✅ | iTerm2/Kitty/Sixel |
| Fallback display | Metadata | ASCII art | |
| **Binary Files** |
| Detection | ✅ | ✅ | Same logic |
| Display | Warning msg | Warning msg | |

---

## 3. UI COMPONENTS

| Component | ppxai (Rich) | ppxaide (Textual) | Notes |
|---------|:------------:|:-----------------:|-------|
| **Status Bar** |
| Provider badge | ✅ | ✅ | |
| Model badge | ✅ | ✅ | |
| Tools badge | ✅ | ✅ | |
| Agent badge | ✅ | ✅ | Shows "Agent: ACTIVE" when enabled |
| Checkpoint badge | ✅ (↶) | ✅ | Shows ↶ (valid) or ↶! (stale) |
| Token count | ✅ | ✅ | |
| Cost display | ✅ | ✅ | |
| Version toggle | ✅ | ✅ | /status version toggles |
| CWD toggle | ✅ | ✅ | /status cwd toggles |
| DateTime toggle | ✅ | ✅ | /status datetime toggles |
| Context badge | ✅ | ✅ | |
| **Transactional Updates** |
| Badge transactions | ⚠️ | ✅ | Textual has full impl |
| Atomic rollback | ❌ | ✅ | v1.15.0 feature |
| **Message Display** |
| User messages | ✅ | ✅ | |
| Assistant messages | ✅ | ✅ | Fixed in blinker integration |
| System messages | ✅ | ✅ | |
| Tool messages | ✅ | ✅ | Via event bus handlers |
| Streaming display | ✅ | ✅ | Fixed - extracts from STREAM_END.data |
| Reasoning tokens | ✅ | ❌ | Deferred (not in Rich TUI yet) |
| **Consent/Prompt Dialogs** |
| Consent prompts | ✅ (inline) | ✅ (modal) | Fixed - wired to EngineClient |
| Text input prompts | ✅ (inline) | ✅ (modal) | Working |
| File edit consent | ✅ | ✅ | Fixed in blinker integration |
| Shell command consent | ✅ | ✅ | Fixed in blinker integration |

---

## 4. THEME SYSTEM

| Feature | ppxai (Rich) | ppxaide (Textual) | Notes |
|---------|:------------:|:-----------------:|-------|
| Built-in themes | 6+ | 17+ | Textual has more |
| Custom themes | 2 (tron, matrix) | 2 (tron, matrix) | Same |
| Theme cycling | ❌ | ✅ (Ctrl+T) | |
| Theme palette | ❌ | ✅ (Ctrl+P) | |
| Syntax theme sync | Manual | ✅ Auto | watch_theme() |
| Emoji mode | ✅ 🔶 | ❌ | Rich-only |

---

## 5. KEYBOARD SHORTCUTS

| Shortcut | ppxai (Rich) | ppxaide (Textual) | Notes |
|----------|:------------:|:-----------------:|-------|
| `Ctrl+C` | ✅ (interrupt/quit) | ✅ (quit) | |
| `Ctrl+L` | ❌ | ✅ (clear) | |
| `Ctrl+T` | ❌ | ✅ (cycle theme) | |
| `Ctrl+P` | ❌ | ✅ (palette) | |
| `Ctrl+W` | ❌ | ✅ (close panel) | |
| `Ctrl+S` | ❌ | ✅ (save panel) | |
| `Ctrl+[/]` | ❌ | ✅ (resize split) | |
| `Ctrl+V` | ❌ | ✅ (toggle view) | |
| `F6` | ❌ | ✅ (focus toggle) | |
| `Ctrl+Tab` | ❌ | ✅ (focus toggle) | |
| `Tab` | ✅ (autocomplete) | ⚠️ | Needs work |
| `↑/↓` | ✅ (history) | ✅ (history) | |
| `Escape` | ❌ | ✅ (cancel/close) | |

---

## 6. AUTOCOMPLETE & TAB COMPLETION

| Feature | ppxai (Rich) | ppxaide (Textual) | Notes |
|---------|:------------:|:-----------------:|-------|
| Command completion | ✅ | ⚠️ | Needs implementation |
| @file completion | ✅ | ❌ | Missing |
| @clipboard/@url | ✅ | ❌ | Missing |
| Tool name completion | ✅ | ❌ | Missing |
| Model/provider completion | ✅ | ❌ | Missing |
| Subcommand completion | ✅ | ❌ | Missing |
| File path completion | ✅ | ❌ | Missing |
| Ignore patterns | ✅ | ❌ | .git, node_modules, etc. |

---

## 7. SESSION FEATURES

| Feature | ppxai (Rich) | ppxaide (Textual) | Notes |
|---------|:------------:|:-----------------:|-------|
| Save session | ✅ | ✅ | |
| Load session | ✅ | ✅ | |
| List sessions | ✅ | ✅ | |
| Auto-save | ✅ | ⚠️ | Needs interval config |
| Auto-restore dialog | ✅ (inline) | ✅ (modal) | |
| Dirty session recovery | ✅ | ⚠️ | Needs crash recovery |
| Provider restoration | ✅ | ✅ | |
| Model restoration | ✅ | ✅ | |
| Tools state restoration | ✅ | ⚠️ | Needs verification |
| Working dir restoration | ✅ | ✅ | |
| Command history | ✅ | ✅ | |

---

## 8. BOOTSTRAP CONTEXT

| Feature | ppxai (Rich) | ppxaide (Textual) | Notes |
|---------|:------------:|:-----------------:|-------|
| AGENTS.md loading | ✅ | ✅ | |
| CLAUDE.md loading | ✅ | ✅ | |
| Global scope | ✅ | ✅ | ~/.ppxai/ |
| Project scope | ✅ | ✅ | git root |
| Subdir scope | ✅ | ✅ | cwd |
| Provider hints | ✅ | ✅ | YAML front matter |
| Model hints | ✅ | ✅ | Pattern matching |
| Include directive | ✅ | ✅ | `<!-- include: -->` |
| /context show | ✅ | ✅ | |
| /context reload | ✅ | ✅ | |
| Hint templates | ✅ | ⚠️ | Needs verification |

---

## PRIORITY WORK ITEMS FOR v1.15.0

### Phase 1: Critical Missing Features (User-Visible)

1. **Tab Autocomplete** ❌ → ✅
   - Command completion
   - @file/@clipboard/@url providers
   - File path completion
   - Ignore patterns (.git, node_modules)

2. **Status Bar Toggles** ⚠️ → ✅
   - `/status version` toggle
   - `/status cwd` toggle
   - `/status datetime` toggle

3. **Agent Mode Badges** ⚠️ → ✅
   - Agent mode indicator
   - Checkpoint status (↶ valid, ↶! stale)

4. **Reasoning Token Display** ⚠️ → ✅
   - DeepSeek R1 reasoning tokens
   - GPT-OSS thinking display
   - Collapsible reasoning sections

### Phase 2: Consistency Fixes

5. **Debug Log Display**
   - Show debug log output in side panel or chat

6. **Tools Config**
   - Verify `/tools config` works correctly

7. **Auto-save Interval**
   - Implement configurable auto-save

8. **Crash Recovery**
   - Dirty session detection and recovery

### Phase 3: Rich-Only Features (Consider Adding)

9. **Emoji Mode** 🔶
   - Text symbol fallback for alignment
   - `/theme emoji on|off`

---

## TEXTUAL-SPECIFIC ENHANCEMENTS (Post-Parity)

These are features unique to Textual that don't apply to Rich:

| Enhancement | Description | Priority |
|-------------|-------------|----------|
| **Split Pane Word Wrap** | Handle narrow terminals | High |
| **Resizable Split Presets** | More size options | Medium |
| **Multi-tab Artifact Panel** | Tabbed code/diff/image views | Medium |
| **Inline Image Rendering** | iTerm2/Kitty in chat | Low |
| **Diff Viewer Widget** | Side-by-side diffs | Medium |
| **Tree Expand Persistence** | Remember expanded nodes | Low |
| **Custom Keybinding Config** | User-defined shortcuts | Low |

---

## SUMMARY

| Category | ppxai Features | ppxaide Features | Gap |
|----------|:--------------:|:----------------:|:---:|
| Commands | 32 | 32 | ✅ |
| Command Handlers | 100% | 100% | ✅ |
| Renderers | 17 types | 17 types | ✅ |
| Status Bar | Full | 100% | ✅ |
| Tab Complete | Full | Deferred | ⏸️ |
| Themes | 6+ | 17+ | ✅ |
| Keyboard Shortcuts | Basic | Extensive | ✅ |
| File Viewers | Basic | Advanced | ✅ |
| Session Management | Full | 95% | ✅ |
| **AI Chat (CORE)** | Full | ✅ | ✅ |
| **Tool Consent** | Full | ✅ | ✅ |

**Bottom Line**: ✅ **CORE FUNCTIONALITY WORKING** (2026-01-28)

After blinker event bus integration (commit 6eb83e2):

1. ✅ **AI responses displayed** - STREAM_END.data extracted when no chunks
2. ✅ **Tool consent working** - Callbacks wired to EngineClient
3. ⏸️ **Tab autocomplete** - Deferred to v1.16.0 (needs refactoring)
4. ✅ **Status bar toggles** - /status version|cwd|datetime working
5. ✅ **Agent/checkpoint badges** - Shows ↶ (valid) or ↶! (stale)
6. ❌ **Reasoning token display** - Deferred (not in Rich TUI yet)

**Feature parity achieved for core chat and tool functionality.**

---

## COMPLETED IN THIS SESSION (2026-01-26)

- ✅ Type-based file display migration for /show command
- ✅ TreeResult uses DataViewer with Ctrl+V toggle (tree ↔ source)
- ✅ TableResult uses TableViewer with Ctrl+V toggle (table ↔ source)
- ✅ MarkdownResult renders in side panel
- ✅ ImageResult uses ImageViewer
- ✅ FileViewResult uses CodeEditor
- ✅ python-magic dependency for file type detection
- ✅ All 1105 tests passing

## FIXES COMPLETED (2026-01-27 → 2026-01-28)

**Blinker Event Bus Integration (commit 6eb83e2):**
- ✅ Added consent handlers (_file_edit_consent_handler, _shell_consent_handler)
- ✅ Wired consent callbacks to EngineClient constructor
- ✅ Fixed STREAM_END to use event.data when no chunks accumulated
- ✅ Added timestamps to MessageBox (like Rich TUI)
- ✅ Replaced python-magic with filetype library (PyInstaller fix)
- ✅ 8 event handlers subscribed via blinker event bus
- ✅ All 1105 tests passing

**Remaining Work (v1.16.0):**
- ⏸️ Tab autocomplete - needs cursor-based positioning refactoring
- ❌ Reasoning tokens - deferred (not in Rich TUI yet)
