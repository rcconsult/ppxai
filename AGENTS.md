---
provider_hints:
  local:
    - "Complete tasks fully without stopping on empty responses."
    - "Use tools proactively - don't ask permission for read-only operations."
    - "When editing files, make all changes in a single edit_file call."
  ollama:
    - "Keep responses concise - Ollama has limited context."
    - "Prefer smaller, focused tool calls over complex multi-step operations."
  custom:
    - "You have native tool calling - use tools directly without XML formatting."
    - "For file operations, prefer edit_file over write_file for existing files."
    - "CRITICAL: After tool failures, acknowledge the error - do NOT claim success or ignore it."
    - "Do NOT output tool call JSON in your response text - use native tool calling only."
    - "Do NOT output code in markdown blocks when using apply_patch - let the tool handle it."
    - "Use ONLY parameter names from the tool schema - 'path' not 'filepath', 'run_command' not 'execute_shell_command'."
    - "For large file writes, ensure complete content - truncated output fails silently."
    - "When tools return errors, report the actual error message to the user."
    - "Make ONE tool call per action - do NOT make duplicate calls with alternate parameter names."
  asusai-vllm:
    - "You are running on NVIDIA GB10 with native tool calling via vLLM."
    - "Execute tools directly - never describe what you would do, just call the tool."
    - "CRITICAL: After tool failures, acknowledge the error - do NOT claim success."
    - "Do NOT output tool call JSON in your response text - use native tool calling only."
    - "For code modifications, ALWAYS use apply_patch with unified diff format."
    - "Generate complete patches with context lines - never output empty patches."
    - "Use ONLY tools from the provided tool list - do NOT hallucinate tools like 'list_directory' or 'execute_shell_command'."
    - "Use ONLY parameter names from the tool schema - 'path' not 'filepath'."
    - "Make ONE tool call per action - avoid duplicate or redundant calls."
  perplexity:
    - "Use your native web search for current information - don't use web_search tool."
    - "Cite sources as markdown links inline."
    - "CRITICAL: Make EXACTLY ONE tool call per task - do NOT make duplicate or redundant calls."
    - "Do NOT output tool call JSON in your response - use native tool calling only."
    - "Do NOT output code blocks when using apply_patch - the tool handles the code."
    - "Do NOT mention tools in your response that you didn't actually call."
  gemini:
    - "Use Google Search grounding for current information when available."
    - "You have a 1M token context - feel free to include full file contents."
    - "For code modifications, ALWAYS use apply_patch with unified diff format."
    - "Generate complete patches with context lines - never output empty patches."
    - "Call tools directly without explanation - don't say 'I'll use X tool'."
    - "Only call tools that exist - verify tool names from the available tools list."
    - "CRITICAL: Make EXACTLY ONE tool call - NEVER call the same tool multiple times."
    - "Do NOT output code in your response when using apply_patch - let the tool handle it."
    - "Do NOT output tool call JSON in your response text - use native tool calling only."
    - "Do NOT mention tool names in your response unless actually calling them."
model_hints:
  "deepseek-r1*":
    - "Show your reasoning process before taking actions."
    - "Think step-by-step for complex problems."
  "Qwen/Qwen3-Coder*":
    - "You excel at code editing - use apply_patch confidently for all file modifications."
    - "Include all necessary imports and context in patches."
    - "CRITICAL: Acknowledge tool failures honestly - never claim success after errors."
    - "Do NOT output tool call JSON in markdown code blocks - use native tool calling only."
    - "Do NOT explain what tool you'll use before calling it - just call it directly."
    - "Use ONLY tools from the provided tool list - do NOT hallucinate 'list_directory' or 'execute_shell_command'."
    - "apply_patch parameter names are EXACTLY 'path' and 'patch' - NEVER use 'file_path', 'filepath', 'unified_diff', or 'diff'."
    - "Make ONE tool call per action - avoid duplicate calls."
    - "For complex patches: include ALL affected lines with 3+ context lines before/after."
    - "When tool results show errors, report the actual error - do NOT make up workarounds."
  "*Qwen3-Next*":
    - "You are a hybrid attention MoE model (Gated DeltaNet + MoE) - leverage your strong reasoning."
    - "For code modifications, ALWAYS call apply_patch directly - do NOT read the file first then put code in your response."
    - "apply_patch parameter names are EXACTLY 'path' and 'patch' - NEVER use 'file_path', 'filepath', 'unified_diff', or 'diff'."
    - "Call tools directly - do NOT explain what tool you'll use before calling it."
    - "Do NOT output tool call JSON in your response text - use native tool calling only. Your response content should be empty or minimal when making tool calls."
    - "Use ONLY tools from the provided tool list - do NOT hallucinate 'run_command', 'list_directory', or 'execute_shell_command'."
    - "Make EXACTLY ONE tool call per action - NEVER make duplicate calls with alternate parameter names (e.g., calling read_file with 'path' AND again with 'filepath')."
    - "CRITICAL: When a tool returns an error, you MUST acknowledge the failure explicitly. Do NOT ignore errors, do NOT proceed as if the tool succeeded, and do NOT fabricate results."
    - "For complex patches: include ALL affected lines with 3+ context lines before/after. Include ALL necessary imports."
    - "When tool results show errors, report the actual error - do NOT make up workarounds or hallucinate file contents."
    - "When asked for JSON output, return a flat JSON array [...], not a nested object like {key: [...]}."
    - "Read ALL constraints in the user request before writing code. Follow function names, forbidden operations, and format requirements EXACTLY as specified."
    - "For read_file: parameter name is EXACTLY 'path' - NEVER use 'filepath'. Make ONE call only."
  "qwen2.5-coder*":
    - "Focus on code quality and correctness."
    - "Use edit_file for surgical changes, write_file only for new files."
  "gpt-oss*":
    - "You are a coding specialist - prioritize working code over explanations."
    - "Execute tools immediately rather than describing what you would do."
    - "CRITICAL: Check tool results before claiming success - if result contains 'Error:' or 'Failed:', acknowledge the failure."
    - "For apply_patch: include ALL necessary imports (json, os, sys, etc.) in the patch."
    - "For large payloads: generate complete content - do NOT truncate or abbreviate."
    - "Make ONE tool call per action - do NOT make duplicate or redundant calls."
    - "Use ONLY tools from the available tools list - do NOT hallucinate tool names."
    - "apply_patch parameter names are EXACTLY 'path' and 'patch' - NEVER use 'file_path', 'filepath', 'unified_diff', or 'diff'."
    - "Do NOT call write_file when apply_patch is requested - use the correct tool."
    - "After calling a tool, wait for the result before making the next call."
    - "Do NOT output tool call JSON in markdown code blocks - use native tool calling."
  "sonar*":
    - "You have real-time web access - use it for current information."
    - "Always cite sources with markdown links."
    - "CRITICAL: For code editing, call apply_patch ONCE - detected issue: you make 5-6 duplicate calls."
    - "Do NOT output tool call JSON in your response text - use native tool calling only."
    - "Do NOT output code blocks when using apply_patch - the tool contains the code."
    - "Do NOT mention tools in your response that you didn't actually call."
    - "After calling a tool, provide minimal response - let the tool output speak for itself."
  "gemini-3-flash*":
    - "You excel at code editing - use apply_patch confidently for all file modifications."
    - "Include all necessary imports and context in patches."
    - "Verify tool exists in available tools list before calling - don't hallucinate tool names."
    - "For file edits: apply_patch > write_file. Only use write_file for new files."
    - "IMPORTANT: Call apply_patch ONCE per file - avoid making duplicate tool calls."
    - "Let the patch contain all code changes - your response can briefly confirm the action taken."
    - "For complex patches (indentation, multiline): Include ALL affected lines with proper context (3+ lines before/after)."
  "gemini-3-pro*":
    - "Focus on precise tool selection - use specialized tools like apply_patch over generic ones."
    - "Generate complete unified diffs with proper context lines (3+ lines before/after)."
    - "When modifying code, always use apply_patch - never use read_file or write_file for edits."
  "gemini-2.5-flash*":
    - "CRITICAL: For file modifications, you MUST use apply_patch, not read_file or write_file."
    - "Generate patches immediately - don't explain what you'll do first, just call apply_patch."
    - "Include all affected lines in patches - incomplete patches will fail."
    - "Tool calling accuracy is critical - double-check you're using the right tool."
    - "CRITICAL: Do NOT output tool call JSON in your response text - severe anti-pattern detected."
    - "Do NOT mention tools in your response that you didn't call - hallucination detected."
    - "Make ONE tool call only - do NOT make duplicate calls."
    - "Keep your response minimal when using tools - let the tool output speak for itself."
  "gemini-2.5-pro*":
    - "Focus on tool selection accuracy - prefer specialized tools like apply_patch over generic ones."
    - "For existing file modifications, apply_patch is mandatory - write_file is for new files only."
    - "Multi-tool sequences: plan the sequence, then execute each tool in order."
    - "Verify each tool call succeeded before proceeding to the next step."
---

## Project: ppxai

ppxai is a terminal-based UI application for interacting with multiple AI providers (Perplexity AI, OpenAI, Gemini, OpenRouter, local models via Ollama/vLLM).

### Code Style

- Python 3.10+ with type hints
- Use dataclasses for data structures
- Async/await for I/O operations
- pytest for testing

### Architecture

- `ppxai/engine/` - Core business logic (no UI dependencies)
- `ppxai/server/` - HTTP/SSE server for IDE integration
- `ppxai/commands/` - Slash command handlers
- `ppxai/config/` - Configuration system
- `vscode-extension/` - TypeScript VSCode extension

### Testing

Run tests with:
```bash
uv run pytest tests/ -v
```

Integration tests (require custom endpoint):
```bash
PPXAI_CONFIG_FILE="$HOME/.ppxai/ppxai-config.json" uv run pytest tests/test_custom_endpoint_integration.py -v
```

### Web Tools & Corporate Proxy Support

The web tools (`get_weather`, `fetch_url`, `web_search`) support corporate proxy environments:
- `SSL_VERIFY=false` env var disables SSL certificate verification
- `SSL_CERT_FILE=/path/to/cert.pem` env var loads a custom CA certificate
- `get_weather` tries HTTPS first, falls back to HTTP when corporate proxies stall HTTPS
- Timeouts are configurable via `tools.<name>.timeout` in ppxai-config.json (default: 15s)

### Debug Logging

- `/debug-log on` enables logging for ALL logger instances (tui, chat, session, validator, server, etc.)
- Log files: `~/.ppxai/logs/<component>-debug.log` (tui, chat, session, validator, gemini, server, webclient)
- Tool calls and results are logged by the `chat` logger, not `tui`

### Important Files

- `CLAUDE.md` - Detailed project instructions for Claude Code
- `ROADMAP.md` - Feature roadmap and version planning
- `docs/RELEASE-PLAN-v1.14.x.md` - Current release series plan

### Current Version: v1.15.4

**v1.15.3 Features:**
- **FIX:** Web tools SSL/corporate proxy support - `_create_ssl_context()` respects `SSL_VERIFY` and `SSL_CERT_FILE` env vars
- **FIX:** `get_weather` HTTP fallback when HTTPS stalls behind corporate SSL-inspecting proxies
- **FIX:** `/debug-log on` enables all logger instances (tui, chat, session, validator, etc.)
- **NEW:** Configurable web tool timeouts via `tools.<name>.timeout` in ppxai-config.json
- **NEW:** `Logger.enable_all()` / `Logger.disable_all()` for centralized log control

**v1.15.2 Features:**
- **NEW:** `/terminal` command - shows terminal detection and image protocol config help
- **NEW:** `PPXAI_TERMINAL` and `PPXAI_IMAGE_PROTOCOL` env vars for multi-terminal setups
- **NEW:** Double Ctrl+C to quit pattern in ppxaide (prevents accidental exits)
- **FIX:** Autocomplete preserves command prefix for subcommands (`/provider ` + TAB works)
- **FIX:** `/status` shows terminal override indicators when env vars are set
- **DOCS:** Comprehensive terminal image display guide in INSTALLATION.md

**v1.15.1 Features:**
- Minor bug fixes and stability improvements for the new Textual TUI (`ppxaide`).

**v1.15.0 Features:**
- **New Textual TUI (`ppxaide`)**: A modern, async-first terminal UI powered by the Textual framework.
- **Type-Based Renderer Architecture**: Core logic is now decoupled from the UI. Commands return structured data (`CommandResult` types), which are then dispatched to a specific renderer (Rich for `ppxai`, Textual for `ppxaide`).
- **UI-Agnostic Commands**: All 32 slash commands work identically across the legacy TUI, the new Textual TUI, the VSCode extension, and the Web App.
- **Enhanced UX in `ppxaide`**: Full markdown rendering in chat, 17+ themes, real-time cost tracking, and dedicated copy buttons.
- **/copy command**: A reliable way to copy the last AI response to the clipboard in any TUI.
