# TUI Command Refactoring - Executive Summary

**Version:** v1.15.0
**Pattern:** Type-Based Renderer Dispatch (Mechanical UI Bindings)

---

## The Big Idea

**Problem:** Commands are tightly coupled to Rich console - can't reuse in Textual TUI.

**Solution:** Commands return **typed result objects**. Each TUI framework registers **renderers** for each type. Dispatch is **mechanical** - zero conditional logic.

```python
# Command returns typed result
def handle_sessions(context, args) -> TableResult:
    sessions = context.engine_client.session.list_sessions()
    return TableResult(
        status=ResultStatus.SUCCESS,
        message=f"{len(sessions)} sessions",
        columns=["Name", "Created", "Provider"],
        rows=[[s.name, s.created, s.provider] for s in sessions]
    )

# TUI frameworks dispatch mechanically
result = handle_sessions(context, args)
RichRenderer.render(result)      # → Rich Table widget
TextualRenderer.render(result)   # → Textual DataTable widget
```

**Result:** Commands work in any TUI. Adding new UI = just write renderers.

---

## Architecture Overview

### 1. Result Type Hierarchy (17 Types)

**Display Results (User Notifications):**
```
├── NotificationResult (success/info/warning toasts)
├── ErrorResult (structured errors with suggestions)
├── ConfirmationResult (action confirmations)
└── AIResponseResult (AI-generated content with markdown)
```

**Structured Data Results:**
```
├── TableResult (tabular data - sessions, tools, stats)
├── TreeResult (hierarchical trees - context, file trees)
├── ListResult (bulleted lists - providers, models)
└── KeyValueResult (config/status pairs)
```

**File & Media Results:**
```
├── FileViewResult (code with syntax highlighting)
└── ImageResult (plots/charts/images from tools)
```

**Operations Results:**
```
├── ProgressResult (long-running operations)
└── DiffResult (before/after changes)
```

**Interactive Results (Phase 2):**
```
├── ConsentResult (user consent requests)
└── PromptResult (text input prompts)
```

**Composite Results (Multi-Artifact Display):**
```
├── CompositeResult (multiple outputs container)
├── ToolExecutionResult (tool execution with artifacts)
└── TextResult (generic fallback - <1% usage)
```

**Each type = formal contract**. Commands emit data, renderers consume data.

### 2. Renderer Pattern

```python
class Renderer:
    _registry: Dict[Type[CommandResult], Callable] = {}

    @classmethod
    def register(cls, result_type):
        """Decorator - register renderer for type."""
        def decorator(func):
            cls._registry[result_type] = func
            return func
        return decorator

    @classmethod
    def render(cls, result):
        """MECHANICAL dispatch - type lookup."""
        result_type = type(result)
        renderer_func = cls._registry[result_type]
        return renderer_func(result)  # No if/else!
```

**Rich TUI:**
```python
@RichRenderer.register(TableResult)
def render_table(result):
    table = Table()
    for col in result.columns: table.add_column(col)
    for row in result.rows: table.add_row(*row)
    console.print(table)
```

**Textual TUI:**
```python
@TextualRenderer.register(TableResult)
async def render_table(renderer, result):
    table = DataTable()
    table.add_columns(*result.columns)
    for row in result.rows: table.add_row(*row)
    await renderer.app.show_widget_in_panel(table)
```

### 3. Command Example (Before/After)

**BEFORE (UI-coupled):**
```python
def handle_sessions(handler, args):
    sessions = handler.engine_client.session.list_sessions()
    from rich.table import Table
    table = Table()  # ❌ Rich-specific
    table.add_column("Name")
    for s in sessions: table.add_row(s.name)
    console.print(table)  # ❌ Direct rendering
```

**AFTER (UI-agnostic):**
```python
def handle_sessions(context, args) -> TableResult:
    sessions = context.engine_client.session.list_sessions()
    return TableResult(
        status=ResultStatus.SUCCESS,
        message=f"{len(sessions)} sessions",
        columns=["Name", "Created", "Provider", "Model"],
        rows=[[s.name, s.created, s.provider, s.model] for s in sessions]
    )  # ✅ Just data
```

---

## File Structure

```
ppxai/
├── commands/
│   ├── results.py (NEW)         # Result type hierarchy
│   ├── protocol.py (NEW)        # CommandContext protocol
│   ├── context.py (NEW)         # Context adapters
│   ├── session.py (REFACTOR)    # Returns TableResult/TextResult
│   ├── provider.py (REFACTOR)   # Returns ListResult/TextResult
│   ├── ...32 commands (REFACTOR)
│   └── factory.py (UPDATE)      # Add clients filter + dispatch
│
├── rendering/ (NEW)
│   ├── base.py                  # Renderer + AsyncRenderer
│   ├── rich_renderer.py         # @RichRenderer.register(...)
│   └── textual_renderer.py      # @TextualRenderer.register(...)
│
├── rich/
│   └── main.py (UPDATE)         # Use RichRenderer.render()
│
└── tui/
    └── app.py (UPDATE)          # Use TextualRenderer.render()
```

**Total:** 6 new files, ~37 files refactored

---

## Command → Result Type Mapping

| Command | Returns | Why This Type |
|---------|---------|---------------|
| `/save`, `/load` | `TextResult` | Simple success/error message |
| `/sessions` | `TableResult` | List of sessions with columns |
| `/tools list` | `TableResult` | Tool name, description, category |
| `/provider list` | `ListResult` | Provider names with icons |
| `/context show` | `TreeResult` | Hierarchical context sources |
| `/version` | `KeyValueResult` | Version, Python, Platform pairs |
| `/show file.py` | `FileViewResult` | Code with syntax highlighting |

---

## Tool Execution Workflow (Multi-Artifact Display)

**Use Case:** Running a pandas script that generates plots, tables, and logs.

### Flow

```python
# 1. Tool executes
tool_result = execute_tool("run_python", "analyze_data.py")

# 2. Tool generates artifacts
artifacts = [
    ImageResult(
        filepath="/tmp/plot.png",
        format="png",
        metadata={"width": 800, "height": 600}
    ),
    TableResult(
        message="Summary Statistics",
        columns=["Metric", "Value"],
        rows=[["Mean", "42.5"], ["Median", "40.0"]]
    ),
    TextResult(
        status=ResultStatus.SUCCESS,
        message="Processing complete"
    )
]

# 3. Wrap in ToolExecutionResult
result = ToolExecutionResult(
    message="Analysis complete",
    tool_name="run_python",
    duration=1.23,
    stdout="Processing 1000 rows...\nDone.",
    exit_code=0,
    artifacts=artifacts
)

# 4. Renderer displays in tabbed panel
await TextualRenderer.render(result)
# → Creates ArtifactPanel with 3 tabs:
#    📊 Image 1 (plot.png)
#    📋 Table 1 (summary stats)
#    📄 Output 1 (processing log)
```

### ArtifactPanel Widget

```python
class ArtifactPanel(TabbedContent):
    """Tabbed panel for multi-artifact display."""

    def add_artifact(self, widget: Widget, title: str, icon: str) -> None:
        """Add artifact as new tab."""

    async def show_artifacts(
        self,
        results: List[CommandResult],
        renderer: TextualRenderer
    ) -> None:
        """Render multiple results as tabs."""
```

**Features:**
- Tab per artifact (image, table, code, etc.)
- Keyboard shortcuts: Ctrl+1/2/3/4/5/6/7/8/9
- Auto-labels with icons
- Hybrid layout: Phase 1 tabbed, Phase 2 optional tiling

---

## Benefits

### 1. Formal Protocol
- Result types = contract between commands and UIs
- Type-safe (mypy validates structure)
- Self-documenting (dataclass fields show what's available)

### 2. Mechanical UI Bindings
- Zero conditional logic: `renderer.render(result)`
- Type dispatch handles routing automatically
- Add new result type → add renderers → all commands work

### 3. Testable Commands
```python
def test_sessions_command():
    context = MockContext()
    result = handle_sessions(context, "")

    assert isinstance(result, TableResult)
    assert result.status == ResultStatus.SUCCESS
    assert len(result.rows) == 3
    # No UI framework needed!
```

### 4. Extensible
- Add web UI? Write `WebRenderer` with HTML/JSON renderers
- Add SSH server? Write `SSHRenderer` with ANSI renderers
- Commands don't change

---

## Migration Plan

### Phase 1: Infrastructure (COMPLETED ✅)
Created new files with 17 result types and complete renderer infrastructure:
- ✅ `ppxai/commands/results.py` (17 result types, 500 lines)
- ✅ `ppxai/commands/protocol.py` (CommandContext protocol, 150 lines)
- ✅ `ppxai/commands/context.py` (Context adapters, 200 lines)
- ✅ `ppxai/rendering/__init__.py` (Package init, 30 lines)
- ✅ `ppxai/rendering/base.py` (Renderer base classes, 150 lines)
- ✅ `ppxai/rendering/rich_renderer.py` (17 handlers, 450 lines)
- ✅ `ppxai/rendering/textual_renderer.py` (17 async handlers, 550 lines)
- ✅ `ppxai/tui/widgets/artifact_panel.py` (Tabbed panel, 250 lines)
- ✅ `tests/commands/test_results.py` (Comprehensive tests, 550 lines)
- ✅ `tests/rendering/test_base.py` (Registry + dispatch tests, 350 lines)

### Phase 2-4: Refactor Commands (6 days)
One category at a time, test after each:
- Session commands (5 commands) → return TextResult/TableResult
- Provider commands (3 commands) → return ListResult/TextResult
- Remaining 24 commands → various result types

### Phase 5: Update TUIs (2 days)
- Rich TUI: `RichRenderer.render(result)`
- Textual TUI: `await TextualRenderer.render(result)`

### Phase 6: Cleanup & Testing (1 day)
- Integration tests
- Update documentation
- Remove old code

**Total: ~10 days** (conservative estimate with thorough testing)

---

## Key Decisions Made

### 1. Result Type Completeness ✅
**Decision:** 17 result types implemented, covering all use cases:
- **Display Results:** NotificationResult, ErrorResult, ConfirmationResult, AIResponseResult
- **Structured Data:** TableResult, TreeResult, ListResult, KeyValueResult
- **File & Media:** FileViewResult, ImageResult
- **Operations:** ProgressResult, DiffResult
- **Interactive:** ConsentResult, PromptResult (Phase 2)
- **Composite:** CompositeResult, ToolExecutionResult, TextResult (fallback)

**Rationale:** Covers all 54 commands + tool execution multi-artifact scenarios.

### 2. Async Strategy
- **Option A:** All commands async (cleaner but bigger change)
- **Option B:** Sync commands + async renderers (proposed - less risk)

### 3. Timeline
- **Conservative:** 10 days (one category per day, thorough tests)
- **Aggressive:** 5 days (batch refactoring, basic tests)

---

## Example: Complete Flow

```python
# 1. User types: /sessions

# 2. TUI dispatches command
result = CommandFactory.dispatch("sessions", context, args)

# 3. Command returns typed result
return TableResult(
    status=ResultStatus.SUCCESS,
    message="3 sessions found",
    columns=["Name", "Created", "Provider"],
    rows=[
        ["session1", "2024-01-20", "perplexity"],
        ["session2", "2024-01-21", "openai"],
        ["session3", "2024-01-22", "gemini"]
    ]
)

# 4. TUI renders mechanically
# Rich TUI:
RichRenderer.render(result)
# → Looks up TableResult in registry
# → Calls render_table(result)
# → Creates Rich Table widget
# → console.print(table)

# Textual TUI:
await TextualRenderer.render(result)
# → Looks up TableResult in registry
# → Calls render_table(renderer, result)
# → Creates DataTable widget
# → Opens in side panel
```

**Zero conditional logic. Pure type dispatch. Mechanical bindings.**

---

## Risks & Mitigation

| Risk | Mitigation | Status |
|------|------------|--------|
| Breaking Rich TUI | Test after each phase, keep old code until new proven | ⏳ Pending Phase 2-4 |
| Async/sync boundary bugs | Comprehensive executor tests, gradual rollout | ✅ Tests complete |
| Missing result types | Started with 17 types covering all scenarios | ✅ Complete |
| Timeline overrun | Conservative estimates, phase-by-phase approval | ✅ Phase 1 on schedule |

---

## Success Criteria

**Phase 1 (Infrastructure):**
- [x] 17 result types implemented with formal contracts
- [x] Renderer base classes with type-based dispatch
- [x] RichRenderer with 17 handlers
- [x] TextualRenderer with 17 async handlers
- [x] ArtifactPanel for multi-artifact display
- [x] Comprehensive test coverage (900+ lines of tests)
- [x] Zero breaking changes to existing code

**Phase 2-4 (Command Refactoring):**
- [ ] All 54 commands return typed results
- [ ] Rich TUI uses `RichRenderer.render()` (mechanical)
- [ ] Textual TUI uses `TextualRenderer.render()` (mechanical)
- [ ] Commands have zero UI dependencies (testable without framework)
- [ ] All existing tests passing
- [ ] Clean architecture: commands → results → renderers → UI

---

## Phase 1 Status: ✅ COMPLETE

**Completed Work:**
- 11 files created (3,680 lines of new code)
- 17 result types covering all command scenarios
- Complete renderer infrastructure (sync + async)
- Multi-artifact display support (ArtifactPanel)
- Comprehensive test coverage (900+ lines)
- Zero breaking changes to existing code

**Key Achievements:**
1. **Type-Based Dispatch Working:** Registry pattern tested and validated
2. **Async Support Proven:** AsyncRenderer handles Textual widget operations
3. **Tool Execution Ready:** ToolExecutionResult + ArtifactPanel for multi-output scenarios
4. **Test Coverage:** All result types and renderer infrastructure fully tested

---

## Next Steps

**Phase 2-4: Command Refactoring**

Start refactoring commands by category:
1. Session commands (5 commands) → TableResult/NotificationResult
2. Provider commands (3 commands) → ListResult/ConfirmationResult
3. Tool commands (7 commands) → TableResult/ToolExecutionResult
4. Remaining commands (39 commands) → Various result types

**Approach:**
- One category at a time
- Test after each category
- Keep old code until new proven
- Gradual rollout to minimize risk

**Estimated Timeline:** 6-8 days for all command refactoring
