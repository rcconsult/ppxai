# Release Plan: v1.12.x Series

**Created:** December 29, 2025
**Last Updated:** January 2, 2026
**Status:** v1.12.1 Released
**Branch:** `master`

---

## Overview

This document outlines the release plan for the v1.12.x series, focusing on:
1. Checkpoint system with stale detection (DONE - v1.12.0)
2. Real-time token usage and cost tracking (DONE - v1.12.0)
3. TUI enhancements: themes, framed panels, clickable links (DONE - v1.12.1)
4. Per-provider/model usage breakdown (NEXT - v1.12.2)
5. Dedicated Gemini provider for native features (PLANNED - v1.12.3+)
6. TUI experiments:
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
- [x] Session usage accumulation
- [x] TUI status line shows `1.2K↓/0.5K↑ $0.0045`
- [x] VSCode usage badge with live updates
- [x] `/usage` command shows session stats
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

## v1.12.2 - Usage Analytics & Cost Breakdown

**Status:** Proposed
**Target:** 1-2 days

### Motivation

Current usage tracking shows only aggregated totals:
```json
{"total_tokens": 1298, "prompt_tokens": 1143, "completion_tokens": 155, "estimated_cost": 0.005754}
```

This is misleading when users switch between providers/models in a session. Different models have vastly different pricing (e.g., sonar: $0.20/M vs sonar-pro: $3.00/M input).

Users also need to track spending over time to budget their API costs effectively.

### Proposed Implementation

#### 1. Session Storage Change

**Current:**
```python
self.usage = UsageStats(...)  # Single aggregate
```

**Proposed:**
```python
self.usage_by_model: Dict[str, UsageStats] = {}  # Key: "provider/model"
# Example keys: "perplexity/sonar-pro", "gemini/gemini-2.0-flash"
```

#### 2. Update `update_usage()` Signature

```python
def update_usage(self, usage: UsageStats, provider: str, model: str):
    key = f"{provider}/{model}"
    if key not in self.usage_by_model:
        self.usage_by_model[key] = UsageStats()

    self.usage_by_model[key].prompt_tokens += usage.prompt_tokens
    self.usage_by_model[key].completion_tokens += usage.completion_tokens
    self.usage_by_model[key].total_tokens += usage.total_tokens
    self.usage_by_model[key].estimated_cost += usage.estimated_cost
```

#### 3. Update `get_usage()` Response

```python
def get_usage(self) -> Dict[str, Any]:
    # Calculate totals
    totals = UsageStats()
    for usage in self.usage_by_model.values():
        totals.prompt_tokens += usage.prompt_tokens
        # ... etc

    return {
        "by_model": {
            key: asdict(usage)
            for key, usage in self.usage_by_model.items()
        },
        "totals": asdict(totals)
    }
```

#### 4. TUI `/usage` Display

```
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃                     Session Usage Statistics                      ┃
┣━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━┳━━━━━━━━━┳━━━━━━━━━━┫
┃ Provider     ┃ Model              ┃ In      ┃ Out     ┃ Cost     ┃
┣━━━━━━━━━━━━━━╋━━━━━━━━━━━━━━━━━━━━╋━━━━━━━━━╋━━━━━━━━━╋━━━━━━━━━━┫
┃ perplexity   ┃ sonar-pro          ┃ 1,143   ┃ 155     ┃ $0.0058  ┃
┃ gemini       ┃ gemini-2.0-flash   ┃ 101     ┃ 3       ┃ $0.0000  ┃
┣━━━━━━━━━━━━━━╋━━━━━━━━━━━━━━━━━━━━╋━━━━━━━━━╋━━━━━━━━━╋━━━━━━━━━━┫
┃ TOTAL        ┃                    ┃ 1,244   ┃ 158     ┃ $0.0058  ┃
┗━━━━━━━━━━━━━━┻━━━━━━━━━━━━━━━━━━━━┻━━━━━━━━━┻━━━━━━━━━┻━━━━━━━━━━┛
```

#### 5. VSCode Extension Usage Tooltip

Hover over usage badge shows breakdown instead of just totals.

#### 6. Status Line (No Change)

Keep showing session totals in status line (space constrained):
```
[Perplexity | sonar-pro | Tools: ON | 1.2K↓/0.5K↑ $0.0058]
```

### Part B: Time-Based Cost Aggregation

#### 1. Persistent Usage Storage

**New File:** `~/.ppxai/usage/usage.json`

```json
{
  "version": 1,
  "sessions": [
    {
      "session_id": "abc123",
      "session_name": "chat-2025-12-29-1430",
      "started_at": "2025-12-29T14:30:00Z",
      "ended_at": "2025-12-29T15:45:00Z",
      "usage_by_model": {
        "perplexity/sonar-pro": {"prompt_tokens": 1143, "completion_tokens": 155, "estimated_cost": 0.0058},
        "gemini/gemini-2.0-flash": {"prompt_tokens": 500, "completion_tokens": 50, "estimated_cost": 0.0001}
      },
      "total_cost": 0.0059
    }
  ]
}
```

#### 2. Time-Based Aggregation

```python
def get_usage_report(period: str = "all") -> Dict[str, Any]:
    """Get usage aggregated by time period.

    Args:
        period: "session" | "24h" | "week" | "month" | "year" | "all"
    """
    now = datetime.now(UTC)
    cutoff = {
        "24h": now - timedelta(hours=24),
        "week": now - timedelta(weeks=1),
        "month": now - timedelta(days=30),
        "year": now - timedelta(days=365),
        "all": datetime.min,
    }.get(period, datetime.min)

    # Filter sessions by cutoff
    sessions = [s for s in usage_data["sessions"] if s["started_at"] >= cutoff]

    return {
        "period": period,
        "session_count": len(sessions),
        "by_model": aggregate_by_model(sessions),
        "by_session": [summarize_session(s) for s in sessions],
        "totals": aggregate_totals(sessions)
    }
```

#### 3. TUI `/usage` Command Enhancement

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
| `ppxai/engine/session.py` | Add `usage_by_model`, update methods |
| `ppxai/engine/client.py` | Pass provider/model to `update_usage()` |
| `ppxai/engine/types.py` | No change (UsageStats stays same) |
| `ppxai/ui.py` | Update `display_usage()` for breakdown table |
| `ppxai/server/http.py` | Update `/usage` endpoint response |
| `vscode-extension/src/chatPanel.ts` | Update usage tooltip |
| `tests/test_session.py` | Add per-model usage tests |
| **NEW** `ppxai/usage.py` | Persistent usage storage and aggregation |
| **NEW** `ppxai/commands.py` | Enhanced `/usage` with period argument |
| **NEW** `vscode-extension/src/usageDashboard.ts` | Usage dashboard webview |

### Effort Estimate

**Part A: Per-Model Breakdown**
- Implementation: 2-3 hours
- Testing: 1 hour
- Subtotal: 3-4 hours

**Part B: Time-Based Aggregation**
- Persistent storage: 2 hours
- Aggregation logic: 2 hours
- TUI enhancements: 2 hours
- VSCode dashboard: 4-6 hours
- HTTP endpoints: 2 hours
- Testing: 2 hours
- Subtotal: 14-16 hours

**Total: 17-20 hours (split across v1.12.1 and v1.12.2)**

### Phased Rollout

| Version | Features |
|---------|----------|
| v1.12.1 | Part A: Per-model breakdown (current session only) |
| v1.12.2 | Part B: Time-based aggregation, persistent storage, `/usage <period>` |
| v1.12.3 | VSCode dashboard webview, CSV export |

---

## v1.12.3 - Time-Based Usage Analytics

**Status:** Planned
**Target:** After v1.12.2

### Features

#### Persistent Usage Storage
- [ ] `~/.ppxai/usage/usage.json` - Session history with costs
- [ ] Auto-save session usage on exit/new session
- [ ] Migration from session-only tracking

#### Time-Based Aggregation
- [ ] `/usage 24h` - Last 24 hours spending
- [ ] `/usage week` - Last 7 days spending
- [ ] `/usage month` - Last 30 days spending
- [ ] `/usage year` - Last 365 days spending
- [ ] `/usage all` - All-time spending

#### HTTP Endpoints
- [ ] `GET /usage/report?period=week` - Time-based report
- [ ] `GET /usage/sessions` - List sessions with costs
- [ ] `GET /usage/export?format=csv` - Export for spreadsheets

### Bug Fixes (TBD based on feedback)
- [ ] Checkpoint edge cases discovered in production
- [ ] Usage tracking accuracy issues
- [ ] VSCode extension UI glitches

---

## v1.12.4 - Gemini Dedicated Provider

**Status:** Planned
**Target:** After v1.12.3

### Motivation

Currently Gemini uses the generic `OpenAICompatibleProvider`. A dedicated provider enables:

| Feature | Generic OpenAI | Dedicated Gemini |
|---------|---------------|------------------|
| Search Grounding | N/A | Real-time web search |
| Safety Settings | N/A | Configurable thresholds |
| Code Execution | N/A | Native Python sandbox |
| System Instructions | Merged into messages | Proper `system_instruction` field |
| Caching | N/A | Context caching for cost reduction |
| Multimodal | Basic | Native image/video/audio |

### What is Search Grounding?

Gemini's Search Grounding connects the model to Google Search in real-time:
- Model can retrieve up-to-date information during generation
- Returns grounding sources (citations) with responses
- Similar to Perplexity's native web search capability
- Reduces hallucination for factual queries

**When enabled:**
```
User: "What's the weather in Tokyo today?"
Gemini: "According to current data, Tokyo is 12°C with partly cloudy skies [1]"
        Sources: [1] weather.google.com
```

### Implementation Plan

**New File:** `ppxai/engine/providers/gemini.py`

### Features to Implement

| Feature | Priority | Effort |
|---------|----------|--------|
| Basic chat with native SDK | High | 2-3 hrs |
| Streaming responses | High | 1-2 hrs |
| Usage/token tracking | High | 1 hr |
| Search grounding | High | 2-3 hrs |
| Grounding source citations | High | 1-2 hrs |
| System instruction handling | Medium | 1 hr |
| Safety settings config | Medium | 1-2 hrs |
| Context caching | Low | 3-4 hrs |
| Code execution | Low | 4-6 hrs |

**Total Effort:** 12-20 hours

### Dependencies

```toml
# pyproject.toml - new optional dependency
[project.optional-dependencies]
gemini = ["google-generativeai>=0.8.0"]
```

---

## v1.12.5 - Gemini Bug Fixes

**Status:** Planned
**Target:** After v1.12.4

### Anticipated Issues
- [ ] Grounding response format changes
- [ ] Rate limiting handling
- [ ] Safety settings edge cases
- [ ] Token counting discrepancies

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
             │  ✅ Real-time token usage and cost tracking
             ▼
Released:    v1.12.1 (2026-01-02) ◄── CURRENT
             │  ✅ TUI themes (Standard, Tron Legacy, Matrix, Nord)
             │  ✅ Framed status panel with badges
             │  ✅ Clickable file links (OSC 8)
             ▼
Next:        v1.12.2 (per-model usage breakdown)
             │  • Track usage by provider/model
             │  • Table display in /usage
             │  • VSCode tooltip breakdown
             ▼
Planned:     v1.12.3 (time-based usage analytics)
             │  • Persistent usage storage
             │  • /usage 24h|week|month|year|all
             │  • Session history with costs
             ▼
Planned:     v1.12.4 (Gemini dedicated provider)
             │  • Native search grounding
             │  • Citation support
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

### Proposed for v1.12.1

6. **Per-Model Usage Breakdown**
   - Track usage by `{provider}/{model}` key
   - Table display in `/usage` command
   - Detailed tooltip in VSCode

### Proposed for v1.12.2

7. **Time-Based Usage Analytics**
   - Persistent storage in `~/.ppxai/usage/usage.json`
   - `/usage 24h|week|month|year|all` commands
   - Session history with cost breakdown
   - CSV export for budgeting

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
