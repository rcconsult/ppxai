# TUI Streaming Rendering Options

This document explains the different approaches for rendering streaming AI responses in the TUI, the trade-offs, and implementation details.

## Context

When using the event-based `EngineClient` architecture (v1.11.1+), the TUI receives streaming responses as a sequence of events:

1. `STREAM_START` - Response begins
2. `STREAM_CHUNK` - Individual text chunks arrive
3. `TOOL_CALL` - AI calls a tool
4. `TOOL_RESULT` - Tool execution completes
5. `STREAM_END` - Response complete, contains full text

The challenge: **How to provide real-time feedback while delivering properly formatted markdown output?**

---

## Option 1: Stream + Format (Current Implementation) ✅

**Approach**: Show raw chunks during streaming (dim style), then render formatted version once complete.

### Implementation

```python
elif event.type == EventType.STREAM_CHUNK:
    # Stream raw chunks in dim style for progress feedback
    console.print(event.data, end="", style="dim")
    full_response += event.data

elif event.type == EventType.STREAM_END:
    console.print("\n")  # Clear line after dim streaming
    # Render final response with proper markdown formatting
    render_markdown_with_tables(full_response, console)
```

### User Experience

```
[dim]This is the streaming response... with tables and markdown...[/dim]

This is the streaming response... with tables and markdown...
┏━━━━━━━━━━┳━━━━━━━━━━━┓
┃ Header 1 ┃ Header 2  ┃
┡━━━━━━━━━━╇━━━━━━━━━━━┩
│ Data 1   │ Data 2    │
└──────────┴───────────┘
```

### Pros
- ✅ **Immediate feedback** - User sees response arriving in real-time
- ✅ **Simple implementation** - Minimal code changes
- ✅ **No flicker** - Static final render
- ✅ **Formatted output** - Tables, headings, code blocks render properly

### Cons
- ⚠️ **Slight duplication** - Content appears twice (once dim, once formatted)
- ⚠️ **Scroll behavior** - Users may need to scroll up to see formatted version
- ⚠️ **Screen space** - Takes more vertical space

### When to Use
- **Best for most use cases** - Good balance of feedback and quality
- When users want to see progress during long responses
- When markdown formatting is important (tables, code blocks)

---

## Option 2: Live Update (In-Place Rendering)

**Approach**: Use Rich's `Live` display to update markdown rendering in-place as chunks arrive.

### Implementation

```python
from rich.live import Live
from rich.markdown import Markdown

with Live(console=console, refresh_per_second=10) as live:
    async for event in engine.chat(message, stream=True):
        if event.type == EventType.STREAM_CHUNK:
            full_response += event.data
            # Update live display with current markdown
            live.update(Markdown(full_response))
        elif event.type == EventType.STREAM_END:
            # Live context exits, final render is displayed
            break
```

### User Experience

```
[Updates in-place every 100ms]
This is the str
This is the streaming re
This is the streaming response...
┏━━━━━━━━━━┳━━━━━━━━━━━┓
┃ Header 1 ┃ Header 2  ┃  [Table renders as markdown arrives]
┡━━━━━━━━━━╇━━━━━━━━━━━┩
```

### Pros
- ✅ **No duplication** - Content only appears once
- ✅ **Real-time formatting** - Markdown renders as it streams
- ✅ **Clean UX** - No dim/bright transition
- ✅ **Space efficient** - No vertical duplication

### Cons
- ⚠️ **Potential flicker** - Tables may redraw as new rows arrive
- ⚠️ **Complexity** - Requires `Live` context management
- ⚠️ **Incomplete markdown** - Partial tables/lists may look broken during streaming
- ⚠️ **Performance** - Re-rendering markdown on every chunk (10 FPS)

### When to Use
- When screen space is critical
- For responses without complex markdown (tables, nested lists)
- When a polished, modern UX is more important than raw speed feedback

---

## Option 3: Progress Indicator (Silent Accumulation)

**Approach**: Show spinner/progress indicator while accumulating, then render formatted result.

### Implementation

```python
from rich.spinner import Spinner

with console.status("[cyan]Generating response...", spinner="dots"):
    async for event in engine.chat(message, stream=True):
        if event.type == EventType.STREAM_CHUNK:
            full_response += event.data
        elif event.type == EventType.STREAM_END:
            break

# Show formatted result after accumulation
render_markdown_with_tables(full_response, console)
```

### User Experience

```
⠋ Generating response...

[Response appears all at once, fully formatted]
This is the streaming response... with tables and markdown...
┏━━━━━━━━━━┳━━━━━━━━━━━┓
┃ Header 1 ┃ Header 2  ┃
┡━━━━━━━━━━╇━━━━━━━━━━━┩
│ Data 1   │ Data 2    │
└──────────┴───────────┘
```

### Pros
- ✅ **Clean output** - No duplication, single formatted render
- ✅ **Simple code** - Just spinner + final render
- ✅ **Professional feel** - Like modern CLI tools (git, npm, etc.)
- ✅ **No flicker** - Static final display

### Cons
- ⚠️ **No preview** - User can't see response content until complete
- ⚠️ **Waiting anxiety** - Long responses feel like the app froze
- ⚠️ **No early feedback** - Can't see tool calls or reasoning chains

### When to Use
- For very short responses (< 2 seconds)
- When formatted output quality is paramount
- For batch operations where streaming feedback is less important

---

## Comparison Matrix

| Aspect | Option 1: Stream + Format | Option 2: Live Update | Option 3: Progress Indicator |
|--------|--------------------------|----------------------|------------------------------|
| **Immediate Feedback** | ✅ Excellent | ✅ Excellent | ❌ None |
| **Output Quality** | ✅ Perfect | ⚠️ Good (may flicker) | ✅ Perfect |
| **Duplication** | ⚠️ Yes (dim + formatted) | ✅ No | ✅ No |
| **Code Complexity** | ✅ Low | ⚠️ Medium | ✅ Low |
| **Screen Space** | ⚠️ Uses more | ✅ Efficient | ✅ Efficient |
| **Markdown Quality** | ✅ Perfect | ⚠️ Partial during stream | ✅ Perfect |
| **User Perception** | ✅ Fast, responsive | ✅ Modern, smooth | ⚠️ May feel slow |

---

## Decision Rationale (v1.11.1)

**We chose Option 1** for the following reasons:

1. **User feedback is critical** - Long responses (10-30s) need progress indication
2. **Simplicity** - Minimal code changes, easy to understand
3. **Reliability** - No flicker or redraw issues
4. **Formatted quality** - Tables and code blocks render perfectly
5. **Acceptable trade-off** - Slight duplication is better than no feedback

### Future Considerations

- **Option 2** could be explored in v1.12+ with improved markdown incremental rendering
- **Option 3** could be offered as a user preference (`ppxai.tui.streamingMode: "live" | "silent" | "dim"`)
- Hybrid approach: Use Option 3 for responses < 2s, Option 1 for longer responses

---

## Related Files

- `ppxai/main.py` (lines 286-317) - Current implementation (Option 1)
- `ppxai/markdown_tables.py` - Markdown rendering with table support
- `ppxai/ui.py` - Rich console utilities

---

## Testing Recommendations

When evaluating streaming options, test with:

1. **Short responses** (< 2 seconds) - Check if streaming overhead is worth it
2. **Long responses** (> 10 seconds) - Verify user doesn't feel app is frozen
3. **Complex markdown** (tables, nested lists, code blocks) - Check rendering quality
4. **Tool calls** (file operations, shell commands) - Ensure tool feedback is visible
5. **Slow connections** - Test with artificial latency (200-500ms per chunk)

---

**Last Updated**: December 22, 2025
**Version**: v1.11.1
**Implemented Option**: Option 1 (Stream + Format)
