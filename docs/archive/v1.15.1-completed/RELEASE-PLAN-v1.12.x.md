# Release Plan: v1.12.x Series

**Created:** December 29, 2025
**Last Updated:** January 3, 2026
**Status:** v1.12.5 Released
**Branch:** `master`

---

## Overview

This document outlines the release plan for the v1.12.x series, focusing on:
1. Checkpoint system with stale detection (DONE - v1.12.0)
2. Real-time token usage and cost tracking with per-model breakdown (DONE - v1.12.0)
3. TUI enhancements: themes, framed panels, clickable links (DONE - v1.12.1)
4. TUI polish: emoji toggle, logging unification, bug fixes (DONE - v1.12.2)
5. Time-based usage analytics (NEXT - v1.12.3)
6. Dedicated Gemini provider for native features (PLANNED - v1.12.4)
7. TUI experiments:
   - `experiment/rich-tui` - MERGED to master (v1.12.1)
   - `experiment/tui-textual` - Experimental, ~20% feature parity

---

## v1.12.0 - Checkpoint System & Usage Tracking

**Status:** ✅ Released (2025-12-31)
**Tag:** v1.12.0

### Features Complete

#### Checkpoint System
- [x] Git-based checkpoints (auto-commit before agent tasks)
- [x] File-based checkpoints (fallback when no git)
- [x] `/undo` command for atomic rollback
- [x] Auto-commit after successful agent tasks
- [x] `EventType.STATUS` for checkpoint notifications
- [x] HTTP endpoints: `/checkpoint/status`, `/checkpoint/undo`
- [x] VSCode Undo button with confirmation dialog
- [x] Collapsible tool messages with verbose mode

#### Checkpoint Stale State Detection (FIXED)
- [x] `is_checkpoint_valid()` checks if checkpoint is HEAD or HEAD~1
- [x] Auto-invalidate stale checkpoints in `get_checkpoint_status()`
- [x] HTTP endpoint rejects undo on stale checkpoints (400 error)
- [x] TUI `/undo` checks validity before reverting
- [x] VSCode Undo button disabled (red) when stale
- [x] 12 new stale detection tests (40 checkpoint tests total)

#### Token Usage & Cost Tracking (FIXED)
- [x] Streaming usage extraction (`stream_options={"include_usage": True}`)
- [x] Cost calculation based on per-model pricing
- [x] **Per-model usage breakdown** (`usage_by_model` dict with `provider/model` keys)
- [x] Session usage accumulation
- [x] TUI status line shows `1.2K↓/0.5K↑ $0.0045`
- [x] VSCode usage badge with live updates
- [x] `/usage` command shows session stats with per-model table
- [x] `/usage show <session|provider|model|off>` display modes
- [x] Works with tools/agent mode (accumulated across iterations)
- [x] Fallback for APIs that don't support `stream_options`
- [x] Self-hosted LLMs: tokens tracked, cost = $0.00

#### Bug Fixes
- [x] `provider_id` → `provider_name` attribute error
- [x] `UsageStats` JSON serialization (use `asdict()`)
- [x] Usage tracking in `_chat_with_tools()` (was missing)

### Tests
- 377 tests passing (12 new checkpoint tests)

---

## v1.12.1 - TUI Enhancements

**Status:** ✅ Released (2026-01-02)
**Tag:** v1.12.1

### Features Complete

- [x] Themed TUI panels with 4 themes: Standard, Tron Legacy, Matrix, Nord
- [x] Framed status panel with colored badges
- [x] Clickable file links via OSC 8 hyperlinks
- [x] `/theme` command with autocomplete
- [x] New files: `ppxai/themes.py`, `ppxai/ui_components.py`

---

## v1.12.2 - TUI Polish & Bug Fixes

**Status:** ✅ Released (2026-01-02)
**Tag:** v1.12.2

### Features Complete

#### Emoji Toggle
- [x] `/theme emoji on|off` command to toggle emoji display in panel badges
- [x] Switch between emoji badges and text-only badges for better alignment

#### Bug Fixes
- [x] **Single-quote JSON** - Fixed parsing of tool calls using single quotes
- [x] **Unified logging** - TUI and engine now share common logger module
- [x] **Logger initialization** - Fixed missing `self.logger` in CommandHandler
- [x] **Checkpoint status** - Shows `↶` symbol instead of full git hash
- [x] **Panel alignment** - Text symbols instead of emojis for consistent alignment

#### Code Cleanup
- [x] Removed obsolete `tui_logger.py` (replaced by `ppxai/common/logger.py`)

### Tests
- 386 tests passing

---

## v1.12.3 - Time-Based Usage Analytics

**Status:** ✅ Released (2026-01-03)
**Tag:** v1.12.3

### Motivation

Per-model usage tracking is complete (v1.12.0), but users need to track spending **over time** to budget their API costs effectively. Currently, usage data is lost when the session ends.

### Proposed Implementation

#### 1. Persistent Usage Storage

**New File:** `~/.ppxai/usage/usage.json`

```json
{
  "version": 1,
  "sessions": [
    {
      "session_id": "abc123",
      "session_name": "chat-2026-01-02-1430",
      "started_at": "2026-01-02T14:30:00Z",
      "ended_at": "2026-01-02T15:45:00Z",
      "usage_by_model": {
        "perplexity/sonar-pro": {"prompt_tokens": 1143, "completion_tokens": 155, "estimated_cost": 0.0058}
      },
      "total_cost": 0.0058
    }
  ]
}
```

#### 2. TUI `/usage` Command Enhancement

```
/usage              # Current session (default)
/usage 24h          # Last 24 hours
/usage week         # Last 7 days
/usage month        # Last 30 days
/usage year         # Last 365 days
/usage all          # All time
```

**Example Output:**
```
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃                    Usage Report: Last 7 Days                              ┃
┣━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┫
┃ Sessions: 12 | Period: Dec 22 - Dec 29, 2025                              ┃
┣━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┫
┃                                                                           ┃
┃ BY PROVIDER/MODEL:                                                        ┃
┣━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━━━━━━┫
┃ Provider     ┃ Model                ┃ Tokens   ┃ Requests ┃ Cost         ┃
┣━━━━━━━━━━━━━━╋━━━━━━━━━━━━━━━━━━━━━━╋━━━━━━━━━━╋━━━━━━━━━━╋━━━━━━━━━━━━━━┫
┃ perplexity   ┃ sonar-reasoning-pro  ┃ 45,230   ┃ 8        ┃ $0.2261      ┃
┃ perplexity   ┃ sonar-pro            ┃ 12,500   ┃ 15       ┃ $0.0500      ┃
┃ gemini       ┃ gemini-2.0-flash     ┃ 8,000    ┃ 10       ┃ $0.0016      ┃
┣━━━━━━━━━━━━━━╋━━━━━━━━━━━━━━━━━━━━━━╋━━━━━━━━━━╋━━━━━━━━━━╋━━━━━━━━━━━━━━┫
┃ TOTAL        ┃                      ┃ 65,730   ┃ 33       ┃ $0.2777      ┃
┗━━━━━━━━━━━━━━┻━━━━━━━━━━━━━━━━━━━━━━┻━━━━━━━━━━┻━━━━━━━━━━┻━━━━━━━━━━━━━━┛
┃                                                                           ┃
┃ BY SESSION:                                                               ┃
┣━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━┫
┃ Session                    ┃ Date         ┃ Messages ┃ Cost              ┃
┣━━━━━━━━━━━━━━━━━━━━━━━━━━━━╋━━━━━━━━━━━━━━╋━━━━━━━━━━╋━━━━━━━━━━━━━━━━━━━┫
┃ chat-2025-12-29-2134       ┃ Dec 29 21:34 ┃ 12       ┃ $0.1579           ┃
┃ chat-2025-12-29-1430       ┃ Dec 29 14:30 ┃ 8        ┃ $0.0505           ┃
┃ chat-2025-12-28-0900       ┃ Dec 28 09:00 ┃ 25       ┃ $0.0693           ┃
┃ ... (9 more sessions)      ┃              ┃          ┃                   ┃
┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━┻━━━━━━━━━━━━━━┻━━━━━━━━━━┻━━━━━━━━━━━━━━━━━━━┛
```

#### 4. VSCode Extension Dashboard

New command: `ppxai.openUsageDashboard`

- Shows usage breakdown in a dedicated webview
- Interactive charts (bar chart by model, line chart over time)
- Period selector: 24h | Week | Month | Year | All
- Export to CSV option

#### 5. HTTP Endpoints

```
GET /usage                    # Current session
GET /usage/report?period=week # Time-based report
GET /usage/sessions           # List all sessions with usage
GET /usage/export?format=csv  # Export usage data
```

### Files to Modify

| File | Changes |
|------|---------|
| **NEW** `ppxai/usage.py` | Persistent usage storage and aggregation |
| `ppxai/commands.py` | Enhanced `/usage` with period argument |
| `ppxai/server/http.py` | New `/usage/report`, `/usage/sessions` endpoints |
| `tests/test_usage.py` | Tests for persistent storage and aggregation |

### Effort Estimate

- Persistent storage: 2 hours
- Aggregation logic: 2 hours
- TUI `/usage <period>` command: 2 hours
- HTTP endpoints: 2 hours
- Testing: 2 hours
- **Total: 8-10 hours**

### Future (v1.12.4+)

| Feature | Description |
|---------|-------------|
| VSCode dashboard | Dedicated webview with charts |
| CSV export | `GET /usage/export?format=csv` |

---

## v1.12.4 - Checkpoint Management Commands

**Status:** ✅ Released (2026-01-03)
**Tag:** v1.12.4

### Features Complete

#### `/checkpoint` Command
- **`/checkpoint status`** - View current checkpoint configuration
- **`/checkpoint list`** - List recent checkpoints (up to 10)
- **`/checkpoint backend <git|file|auto|none>`** - Switch checkpoint backend (session-only)
- **`/checkpoint clear`** - Clear old file-based checkpoint snapshots
- **`/checkpoint info <id>`** - Show details about a specific checkpoint
- **`/checkpoint undo`** - Alias for `/undo` command
- **Tab autocomplete** - Subcommands and backend options autocomplete in TUI

#### Web Search Tool Upgrade
- **`ddgs` package** - Upgraded to use `ddgs>=9.0.0` for more reliable DuckDuckGo search
- **Fallback chain** - Uses ddgs → duckduckgo-search → HTML scraping

#### VSCode Extension
- All `/checkpoint` commands available in extension
- HTTP endpoints: `/checkpoint/list`, `/checkpoint/backend`, `/checkpoint/clear`

#### Documentation
- Updated [checkpoint-guide.md](checkpoint-guide.md) to v1.12.4

### Tests
- 400 tests passing

---

## v1.12.5 - Native Gemini Provider

**Status:** ✅ Released (2026-01-03)
**Tag:** v1.12.5

### Features Complete

#### Google Search Grounding
- **Native Gemini SDK** - Direct integration with `google-genai` package
- **Google Search Grounding** - Real-time web search with citations (like Perplexity)
- **Streaming support** - Full async streaming with usage tracking
- **Graceful fallback** - Uses OpenAI-compatible API if `google-genai` not installed

#### Installation
```bash
pip install ppxai[gemini]   # For enhanced Gemini support
```

#### Provider Features
- Search grounding with citation support
- Native streaming responses
- Token usage tracking
- Safety settings configuration
- System instruction handling

### Tests
- 406 tests passing

---

## TUI Enhancement Experiments

**Status:** Experimental
**Branches:** `experiment/rich-tui`, `experiment/tui-textual`

### Motivation

The current TUI uses Rich for rendering but doesn't leverage its full potential. The VSCode extension has a polished UI with message boxes, badges, and visual hierarchy. We want to bring that experience to the terminal.

Two experimental approaches will be evaluated:

### Experiment 1: Enhanced Rich TUI

**Branch:** `experiment/rich-tui`
**Framework:** Rich (current dependency)
**Effort:** 4-6 hours

Uses Rich's advanced components (Panel, Live, Layout) to enhance the existing TUI without introducing new dependencies.

#### UI Components

```python
from rich.panel import Panel
from rich.markdown import Markdown
from rich import box
from rich.text import Text
from rich.table import Table

def render_message(role: str, content: str, theme: Theme) -> Panel:
    """Render a message with rounded corners and theme colors."""
    style = theme.user_style if role == "user" else theme.assistant_style
    title = theme.user_title if role == "user" else theme.assistant_title
    return Panel(
        Markdown(content),
        title=f"[bold]{title}[/bold]",
        border_style=style,
        box=box.ROUNDED,  # ╭──╮ rounded corners
        padding=(0, 1)
    )

def render_header(provider: str, model: str, tools: bool, usage: str, theme: Theme) -> Panel:
    """Render status bar with badges."""
    header = Table.grid(expand=True)
    header.add_column(justify="left")
    header.add_column(justify="right")

    badges = Text()
    badges.append(f" {provider} ", style=theme.provider_badge)
    badges.append(" ")
    badges.append(f" {model} ", style=theme.model_badge)
    badges.append(" ")
    badges.append(f" Tools: {'ON' if tools else 'OFF'} ",
                  style=theme.tools_on_badge if tools else theme.tools_off_badge)
    badges.append(" ")
    badges.append(f" {usage} ", style=theme.usage_badge)

    header.add_row(f"ppxai v1.12.x", badges)
    return Panel(header, box=box.ROUNDED, style=theme.header_style)
```

#### Theme System

```python
from dataclasses import dataclass

@dataclass
class Theme:
    """TUI theme configuration."""
    name: str

    # Message styles
    user_style: str
    user_title: str
    assistant_style: str
    assistant_title: str

    # Badge styles (Rich markup)
    provider_badge: str
    model_badge: str
    tools_on_badge: str
    tools_off_badge: str
    usage_badge: str

    # Header/footer
    header_style: str
    footer_style: str

    # Code blocks
    code_theme: str  # Pygments theme name

# Built-in themes
THEMES = {
    "standard": Theme(
        name="Standard",
        user_style="blue",
        user_title="You",
        assistant_style="green",
        assistant_title="Assistant",
        provider_badge="white on blue",
        model_badge="white on dark_blue",
        tools_on_badge="white on green",
        tools_off_badge="white on red",
        usage_badge="white on dark_green",
        header_style="dim",
        footer_style="dim",
        code_theme="monokai",
    ),
    "tron-legacy": Theme(
        name="Tron Legacy",
        # Tron Legacy color palette
        # Cyan: #6FC3DF (user)
        # Orange: #DF740C (system/warnings)
        # White: #F8F8F8 (text)
        # Dark: #0C141F (background implied)
        user_style="cyan",
        user_title="USER",
        assistant_style="bright_cyan",
        assistant_title="PROGRAM",
        provider_badge="black on cyan",
        model_badge="black on bright_cyan",
        tools_on_badge="black on bright_green",
        tools_off_badge="black on red",
        usage_badge="black on yellow",
        header_style="cyan dim",
        footer_style="cyan dim",
        code_theme="native",  # Dark theme for code
    ),
}
```

#### Files to Modify

| File | Changes |
|------|---------|
| `ppxai/ui.py` | Add `Theme` dataclass, `render_message()`, `render_header()` |
| `ppxai/main.py` | Load theme from config, pass to UI functions |
| `ppxai/config.py` | Add `tui.theme` config option |
| **NEW** `ppxai/themes.py` | Theme definitions (standard, tron-legacy) |

---

### Experiment 2: Textual TUI

**Branch:** `experiment/tui-textual`
**Framework:** Textual (new dependency)
**Effort:** 8-12 hours

Full rewrite using Textual framework for a modern, reactive TUI with mouse support, scrolling, and CSS styling.

#### Why Textual?

| Feature | Rich | Textual |
|---------|------|---------|
| Output rendering | ✅ | ✅ |
| Interactive widgets | ❌ | ✅ |
| Mouse support | ❌ | ✅ |
| CSS styling | ❌ | ✅ |
| Scrollable views | Manual | ✅ Built-in |
| Layout system | Basic | ✅ Flexbox-like |
| Hot reload | ❌ | ✅ |
| Component lifecycle | ❌ | ✅ |

#### App Structure

```python
from textual.app import App, ComposeResult
from textual.containers import ScrollableContainer, Horizontal
from textual.widgets import Header, Footer, Static, Input, Button
from textual.css.query import NoMatches

class MessageBox(Static):
    """A styled message container."""

    def __init__(self, role: str, content: str) -> None:
        super().__init__()
        self.role = role
        self.content = content
        self.add_class(f"message-{role}")

    def compose(self) -> ComposeResult:
        yield Static(self.content, classes="message-content")

class StatusBadge(Static):
    """A status indicator badge."""
    pass

class PPXAIApp(App):
    """Main TUI application."""

    CSS_PATH = "ppxai.tcss"
    BINDINGS = [
        ("ctrl+c", "quit", "Quit"),
        ("ctrl+t", "toggle_tools", "Toggle Tools"),
        ("escape", "cancel", "Cancel"),
    ]

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal(id="status-bar"):
            yield StatusBadge("Perplexity", id="provider-badge")
            yield StatusBadge("sonar-pro", id="model-badge")
            yield StatusBadge("Tools: ON", id="tools-badge")
            yield StatusBadge("1.2K↓/0.5K↑ $0.00", id="usage-badge")
        yield ScrollableContainer(id="chat-history")
        yield Input(placeholder="Type a message...", id="chat-input")
        yield Footer()

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle user message submission."""
        message = event.value
        event.input.value = ""

        # Add user message to chat
        chat = self.query_one("#chat-history")
        chat.mount(MessageBox("user", message))

        # Stream AI response...
```

#### Theme CSS (ppxai.tcss)

```css
/* Standard Theme */
.message-user {
    border: round cyan;
    margin: 1 2;
    padding: 0 1;
}

.message-assistant {
    border: round green;
    margin: 1 2;
    padding: 0 1;
}

#status-bar {
    dock: top;
    height: 1;
    background: $surface;
}

StatusBadge {
    padding: 0 1;
    margin: 0 1;
}

#provider-badge {
    background: blue;
    color: white;
}

#model-badge {
    background: darkblue;
    color: white;
}

#tools-badge.on {
    background: green;
    color: white;
}

#tools-badge.off {
    background: red;
    color: white;
}

/* Tron Legacy Theme */
.tron-legacy .message-user {
    border: round $accent;
    border-title-color: $accent;
}

.tron-legacy .message-assistant {
    border: round $secondary;
}

.tron-legacy {
    /* Tron Legacy palette */
    $primary: #0C141F;
    $accent: #6FC3DF;
    $secondary: #DF740C;
    $text: #F8F8F8;
}
```

#### Files to Create

| File | Purpose |
|------|---------|
| **NEW** `ppxai/tui/__init__.py` | TUI package |
| **NEW** `ppxai/tui/app.py` | Main Textual app |
| **NEW** `ppxai/tui/widgets.py` | Custom widgets (MessageBox, StatusBadge) |
| **NEW** `ppxai/tui/themes/` | Theme CSS files |
| **NEW** `ppxai/tui/themes/standard.tcss` | Standard theme |
| **NEW** `ppxai/tui/themes/tron-legacy.tcss` | Tron Legacy theme |

---

### UI Design Guidelines (Both Experiments)

#### 1. Visual Alignment with VSCode Extension

| Element | VSCode | TUI Target |
|---------|--------|------------|
| Message boxes | Bordered cards | `Panel(box=box.ROUNDED)` or Textual border |
| User messages | Blue accent | Blue border/background |
| Assistant messages | Green accent | Green border/background |
| Status badges | Colored pills | Inline colored text blocks |
| Provider/Model | Header badges | Top status bar |
| Tools toggle | Clickable button | Badge + `/tools` command |
| Usage display | Badge + tooltip | Badge in status bar |

#### 2. Rounded Corners

**Rich:** Use `box=box.ROUNDED` for Panel components
```
╭─ You ──────────────────────────────────────╮
│ What is the capital of France?             │
╰────────────────────────────────────────────╯
```

**Textual:** Use `border: round <color>;` in CSS
```css
.message-user {
    border: round cyan;
}
```

#### 3. Theme Support

Both experiments must support switching between themes at runtime:

```bash
# TUI command
/theme standard
/theme tron-legacy
/theme list

# Config file
{
    "tui": {
        "theme": "tron-legacy"
    }
}
```

#### 4. DAG-Style Refactoring Protection

To avoid breaking existing functionality, follow this dependency structure:

```
┌─────────────────────────────────────────────────────────────────┐
│                        ppxai/ui.py                              │
│  (Current rendering - PROTECTED, minimal changes)               │
└─────────────────────────────────────────────────────────────────┘
                              │
                              │ imports
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                     ppxai/ui_components.py                      │
│  (NEW: Shared components - Theme, MessageRenderer, BadgeRenderer)│
└─────────────────────────────────────────────────────────────────┘
                              │
              ┌───────────────┴───────────────┐
              │                               │
              ▼                               ▼
┌─────────────────────────┐     ┌─────────────────────────┐
│  ppxai/ui_rich.py       │     │  ppxai/tui/app.py       │
│  (Experiment 1: Rich)    │     │  (Experiment 2: Textual)│
└─────────────────────────┘     └─────────────────────────┘
```

**Refactoring Rules:**
1. **DO NOT** modify core rendering in `ppxai/ui.py` directly
2. **DO** extract shared components to `ppxai/ui_components.py`
3. **DO** create new modules for experimental UI code
4. **DO** use feature flags or entry points to switch implementations
5. **DO** maintain backward compatibility with existing config

---

### Comparison Workflow

**Note:** Both experiment branches remain open until a decision is made. No merge until comparison is complete.

1. **Phase 1: Rich Experiment** (`experiment/rich-tui`)
   - Branch from current `master` or `feature/agent-multi-file-atomic-edit`
   - Implement enhanced Rich UI with rounded panels
   - Add theme support (standard, tron-legacy)
   - Keep branch open for testing

2. **Phase 2: Textual Experiment** (`experiment/tui-textual`)
   - Branch from `experiment/rich-tui` (inherit theme system)
   - Implement full Textual app
   - Keep branch open for testing

3. **Phase 3: Side-by-Side Testing**
   - Both branches available for testing
   - Compare implementation complexity
   - Compare user experience (responsiveness, mouse support)
   - Compare maintenance burden (dependencies, testing)
   - Gather feedback from actual usage

4. **Phase 4: Decision & Merge**
   - Choose winner: Rich enhancement OR Textual migration
   - Merge chosen experiment to main branch
   - Archive (don't delete) rejected experiment branch
   - Release as v1.12.5 or v1.13.0

---

### Tron Legacy Color Palette Reference

From the movie's visual design:

| Element | Hex | RGB | Rich Color |
|---------|-----|-----|------------|
| Cyan (User) | #6FC3DF | 111, 195, 223 | `cyan` / `bright_cyan` |
| Orange (Flynn) | #DF740C | 223, 116, 12 | `dark_orange` |
| White (Grid) | #F8F8F8 | 248, 248, 248 | `white` |
| Dark (Background) | #0C141F | 12, 20, 31 | Terminal default |
| Blue (Identity Disc) | #18CAE6 | 24, 202, 230 | `bright_cyan` |
| Red (Enemy) | #FF4500 | 255, 69, 0 | `red` |

---

## Future Considerations (v1.13+)

### Claude/Anthropic Dedicated Provider

**Priority:** Low (ppxai is not competing with Claude Code)

| Feature | Value for ppxai |
|---------|-----------------|
| Prompt caching | Up to 90% cost reduction |
| Extended thinking | Chain-of-thought visibility |
| Native tool use | Better tool calling format |

### AGENTS.md Support

As planned in ROADMAP.md:
- Load project context on startup
- File precedence (global → project → subdirectory)
- `/agents show`, `/agents reload`, `/agents edit` commands

---

## Release Checklist Template

For each release:

- [ ] All tests passing (377+ tests)
- [ ] Update version in:
  - [ ] `pyproject.toml`
  - [ ] `vscode-extension/package.json`
  - [ ] `ppxai/__init__.py`
  - [ ] `CLAUDE.md`
  - [ ] `ROADMAP.md`
- [ ] Create release notes: `docs/RELEASE-NOTES-v{version}.md`
- [ ] Run `/release v{version}` skill
- [ ] Verify CI builds pass
- [ ] Verify GitHub release marked as "Latest"
- [ ] Test TUI and VSCode extension manually
- [ ] Update documentation if needed

---

## Timeline Summary

```
Released:    v1.12.0 (2025-12-31)
             │  ✅ Checkpoint system with stale detection
             │  ✅ Real-time token usage + per-model breakdown
             ▼
Released:    v1.12.1 (2026-01-02)
             │  ✅ TUI themes (Standard, Tron Legacy, Matrix, Nord)
             │  ✅ Framed status panel with badges
             │  ✅ Clickable file links (OSC 8)
             ▼
Released:    v1.12.2 (2026-01-02)
             │  ✅ Bug fixes (JSON parsing, logging)
             │  ✅ /theme emoji on|off command
             │  ✅ Panel alignment improvements
             ▼
Released:    v1.12.3 (2026-01-03)
             │  ✅ Persistent usage storage
             │  ✅ /usage 24h|week|month|year|all
             │  ✅ Session history with costs
             ▼
Released:    v1.12.4 (2026-01-03)
             │  ✅ /checkpoint management commands
             │  ✅ Web search tool upgrade (ddgs)
             │  ✅ Tab autocomplete for checkpoints
             ▼
Released:    v1.12.5 (2026-01-03) ◄── CURRENT
             │  ✅ Native Gemini provider
             │  ✅ Google Search Grounding
             │  ✅ Citation support
             ▼
Future:      v1.13.0 (AGENTS.md support)

═══════════════════════════════════════════════════════════════════
                    TUI EXPERIMENTS
═══════════════════════════════════════════════════════════════════

✅ MERGED: experiment/rich-tui → master (v1.12.1)
           │  • Rich SDK enhancements
           │  • Rounded panel message boxes
           │  • 4 themes (Standard, Tron Legacy, Matrix, Nord)
           │  • Framed status bar with badges

🧪 OPEN:   experiment/tui-textual
           │  • Full Textual framework
           │  • ~20% feature parity with Rich TUI
           │  • Missing: autocomplete, commands, agent mode
           │  • Decision: Keep as experiment, no merge planned
```

---

## Summary of Changes in This Session

### Completed Today (Dec 29, 2025)

1. **Checkpoint Stale Detection** - CRITICAL bug fixed
   - `is_checkpoint_valid()` in checkpoint backends
   - Auto-invalidation in `get_checkpoint_status()`
   - TUI and VSCode protection against stale undo
   - 12 new tests

2. **Usage Tracking Bugs** - FIXED
   - `provider_id` → `provider_name` typo
   - `UsageStats` JSON serialization
   - Usage tracking in `_chat_with_tools()` (was completely missing)
   - `stream_options` fallback for vLLM/Ollama
   - VSCode usage badge now updates after each response

3. **UI Improvements**
   - TUI status line: checkpoint ID with validity colors
   - VSCode Undo button: grey/blue/red based on state
   - VSCode table CSS: horizontal scroll for wide tables

4. **Concurrent Request Protection** - NEW
   - VSCode input disabled during streaming/consent
   - Session cleanup on 400 message alternation errors
   - Prevents accidental duplicate messages

5. **Context Injection Fix** - NEW
   - `@tree` and `@git` now work correctly in VSCode extension
   - Previously treated as file search instead of context providers

### Released in v1.12.0

6. **Per-Model Usage Breakdown** ✅
   - Track usage by `{provider}/{model}` key
   - Table display in `/usage` command
   - `/usage show <session|provider|model|off>` display modes

### Released in v1.12.1 ✅

7. **TUI Themes & Polish**
   - 4 themes: Standard, Tron Legacy, Matrix, Nord
   - Framed status panel with badges
   - Clickable file links (OSC 8)

### Released in v1.12.2 ✅

8. **Bug Fixes & Code Cleanup**
   - Single-quote JSON parsing fix
   - Unified logging (TUI + engine)
   - `/theme emoji on|off` command

### Next: v1.12.3

9. **Time-Based Usage Analytics**
   - Persistent storage in `~/.ppxai/usage/usage.json`
   - `/usage 24h|week|month|year|all` commands
   - Session history with cost breakdown

---

## Release Checklist (Template)

Use for each new release:

```bash
# 1. Create release notes
# Edit docs/RELEASE-NOTES-v{version}.md

# 2. Run validation
python scripts/validate-release.py v{version}

# 3. Execute release
/release v{version}
# or: python scripts/release.py v{version}

# 4. Verify on GitHub
# https://github.com/rcconsult/ppxai/releases/tag/v{version}
```

---

**Last Updated:** January 2, 2026
