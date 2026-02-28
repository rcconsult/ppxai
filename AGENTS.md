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
    - "Do NOT make duplicate calls with alternate parameter names. Chain multiple DIFFERENT tool calls without stopping."
  asusai-vllm:
    - "You are running on NVIDIA GB10 with native tool calling via vLLM."
    - "Execute tools directly - never describe what you would do, just call the tool."
    - "CRITICAL: After tool failures, acknowledge the error - do NOT claim success."
    - "Do NOT output tool call JSON in your response text - use native tool calling only."
    - "For code modifications, ALWAYS use apply_patch with unified diff format."
    - "Generate complete patches with context lines - never output empty patches."
    - "Use ONLY tools from the provided tool list - do NOT hallucinate tools like 'list_directory' or 'execute_shell_command'."
    - "Use ONLY parameter names from the tool schema - 'path' not 'filepath'."
    - "Avoid duplicate or redundant calls. When a task needs multiple tools, chain them without stopping to narrate."
    - "COMPLETE ALL STEPS. Never stop a multi-step task early. If the task is write→test→fix→retest, do all 4 steps."
    - "Explore thoroughly: list subdirectories, not just the top level. Read ALL relevant files before summarizing."
  perplexity:
    - "Use your native web search for current information - don't use web_search tool."
    - "Cite sources as markdown links inline."
    - "CRITICAL: Do NOT make duplicate calls for the same operation. Chain multiple DIFFERENT tool calls without stopping to narrate."
    - "To call a tool, output ONLY the JSON object with 'tool' and 'arguments' keys — no surrounding text, no markdown code fences."
    - "Keep tool calls small. For apply_patch: use focused patches on specific sections, NOT full file rewrites."
    - "If a tool call fails or is truncated, try a DIFFERENT approach — do NOT repeat the same large call."
    - "Do NOT mention tools in your response that you didn't actually call."
  openai:
    - "You have native function calling - ALWAYS use the tools API to call tools. NEVER output tool call JSON like {\"tool\": \"...\", \"arguments\": {...}} in your response text."
    - "For code modifications, ALWAYS use apply_patch with unified diff format. Do NOT use read_file when you should be editing."
    - "Generate complete patches with context lines (3+ lines before/after) - never output empty patches."
    - "Call tools directly without explanation - don't say 'I'll use X tool' then output JSON."
    - "CRITICAL: Do NOT make duplicate calls for the same operation. Chain multiple DIFFERENT tool calls without stopping to narrate."
    - "CRITICAL: When a tool returns an error, ACKNOWLEDGE the failure to the user. After 2 consecutive failures of the same tool, STOP retrying and report the persistent issue."
    - "Do NOT output code blocks in your response when using apply_patch - the tool contains the code."
    - "Do NOT mention tools in your response that you didn't actually call."
    - "Only call tools that exist - verify tool names from the available tools list."
    - "apply_patch parameter names are EXACTLY 'path' and 'patch' - NEVER use 'file_path', 'filepath', or 'diff'."
    - "For large file writes (50+ lines), ensure the COMPLETE content is in the tool call arguments - never truncate."
  gemini:
    - "Use Google Search grounding for current information when available."
    - "You have a 1M token context - feel free to include full file contents."
    - "For code modifications, ALWAYS use apply_patch with unified diff format."
    - "Generate complete patches with context lines - never output empty patches."
    - "Call tools directly without explanation - don't say 'I'll use X tool'."
    - "Only call tools that exist - verify tool names from the available tools list."
    - "CRITICAL: NEVER call the same tool with the same arguments twice. Use the result from the first call and move on. But DO chain multiple DIFFERENT tool calls without stopping."
    - "Do NOT output code in your response when using apply_patch - let the tool handle it."
    - "Do NOT output tool call JSON in your response text - use native tool calling only."
    - "Do NOT mention tool names in your response unless actually calling them."
    - "When a tool result shows an error or failure, ALWAYS acknowledge it in your response before taking further action."
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
    - "Avoid duplicate tool calls. Chain multiple DIFFERENT tool calls without stopping to narrate."
    - "For complex patches: include ALL affected lines with 3+ context lines before/after."
    - "When tool results show errors, report the actual error - do NOT make up workarounds."
    - "NEVER stop mid-chain. When a task has multiple steps (write→test→fix→retest), complete ALL steps. After writing code, ALWAYS run the tests. After test failure, fix the code and retest."
    - "When asked to review or find multiple files, read ALL of them. List subdirectories and explore them too — don't stop after the first directory."
    - "When reporting status across multiple steps, track each step individually. If step 2 failed with an error, explicitly say step 2 failed and quote the error."
    - "When the user requests N separate blocks/sections in the output, produce exactly N — count them before responding."
  "*Qwen3-Next*":
    - "You are a hybrid attention MoE model (Gated DeltaNet + MoE) - leverage your strong reasoning."
    - "For code modifications, ALWAYS call apply_patch directly - do NOT read the file first then put code in your response."
    - "apply_patch parameter names are EXACTLY 'path' and 'patch' - NEVER use 'file_path', 'filepath', 'unified_diff', or 'diff'."
    - "Call tools directly - do NOT explain what tool you'll use before calling it."
    - "Do NOT output tool call JSON in your response text - use native tool calling only. Your response content should be empty or minimal when making tool calls."
    - "Use ONLY tools from the provided tool list - do NOT hallucinate 'run_command', 'list_directory', or 'execute_shell_command'."
    - "NEVER make duplicate calls with alternate parameter names (e.g., calling read_file with 'path' AND again with 'filepath'). Chain multiple DIFFERENT tool calls without stopping."
    - "CRITICAL: When a tool returns an error, you MUST acknowledge the failure explicitly. Do NOT ignore errors, do NOT proceed as if the tool succeeded, and do NOT fabricate results."
    - "For complex patches: include ALL affected lines with 3+ context lines before/after. Include ALL necessary imports."
    - "When tool results show errors, report the actual error - do NOT make up workarounds or hallucinate file contents."
    - "When asked for JSON output, return a flat JSON array [...], not a nested object like {key: [...]}."
    - "Read ALL constraints in the user request before writing code. Follow function names, forbidden operations, and format requirements EXACTLY as specified."
    - "For read_file: parameter name is EXACTLY 'path' - NEVER use 'filepath'."
  "qwen2.5-coder*":
    - "Focus on code quality and correctness."
    - "Use edit_file for surgical changes, write_file only for new files."
  "gpt-oss*":
    - "You are a coding specialist - prioritize working code over explanations."
    - "Execute tools immediately rather than describing what you would do."
    - "CRITICAL: Check tool results before claiming success - if result contains 'Error:' or 'Failed:', acknowledge the failure."
    - "For apply_patch: include ALL necessary imports (json, os, sys, etc.) in the patch."
    - "For large payloads: generate complete content - do NOT truncate or abbreviate."
    - "Do NOT make duplicate or redundant calls. Chain multiple DIFFERENT tool calls without stopping."
    - "Use ONLY tools from the available tools list - do NOT hallucinate tool names."
    - "apply_patch parameter names are EXACTLY 'path' and 'patch' - NEVER use 'file_path', 'filepath', 'unified_diff', or 'diff'."
    - "Do NOT call write_file when apply_patch is requested - use the correct tool."
    - "After calling a tool, wait for the result before making the next call."
    - "Do NOT output tool call JSON in markdown code blocks - use native tool calling."
  "gpt-5.2*":
    - "You are the newest OpenAI flagship - prioritize precise, complete tool calls."
    - "For code modifications, use apply_patch with complete unified diffs including ALL context lines (3+ before/after each change)."
    - "CRITICAL: Do NOT output tool call JSON in your response text. Use the tools API to make function calls."
    - "CRITICAL: When a tool returns an error or failure, TELL THE USER what went wrong. Do NOT silently retry without acknowledging the error."
    - "After 2 consecutive failures of the same operation, STOP and report the persistent issue instead of retrying."
    - "Call tools directly - do NOT explain what you'll do first."
    - "Avoid duplicate or redundant calls for the same operation."
    - "For large file writes: ensure the COMPLETE content is in the tool call - never truncate or abbreviate."
    - "CRITICAL: When a task requires multiple file operations, chain ALL tool calls consecutively. After receiving a tool result, immediately make the next tool call. Do NOT stop to narrate or summarize between tool calls."
    - "When asked to read multiple files, call read_file for EACH file before responding."
  "gpt-5.1-codex-mini*":
    - "You are a lightweight code-specialized model with native function calling. Call tools directly — never output JSON in your response text."
    - "CRITICAL: Tools are available — CALL them. Do NOT say 'I don't have access' or 'no tools provided'."
    - "Do NOT ask for confirmation or permission before using tools. Call tools immediately without explaining what you plan to do."
    - "For file modifications, use apply_patch with unified diff format. Include 3+ context lines."
    - "Chain consecutive tool calls for DIFFERENT files without stopping to narrate between them."
    - "Keep responses concise — focus on executing the task, not explaining what you'll do."
  "gpt-5.1-codex*":
    - "You are a code-specialized model with native function calling. You MUST call tools directly when tasks require file operations."
    - "CRITICAL: When asked to read a file, CALL the read_file function. When asked to edit code, CALL apply_patch. Do NOT say 'I don't have access' - you have function calling tools available."
    - "CRITICAL: You MUST proactively call tools to complete tasks. Never respond with 'I haven't run any tools' or 'no tool results were provided' - USE the tools."
    - "CRITICAL: NEVER re-read a file you already read or re-list a directory you already listed. Use the result from the first call and move on to the NEXT step."
    - "For ALL file modifications, use apply_patch with unified diff format including 3+ context lines."
    - "Chain tool calls for DIFFERENT files consecutively. Do NOT stop to narrate between tool calls."
    - "Execute tools immediately - never describe what you would do, just call the function."
    - "When a tool returns an error, acknowledge the failure and try a DIFFERENT approach — do NOT repeat the same call."
  "gpt-5-mini*":
    - "Do NOT ask permission before using tools. Call tools immediately without explaining."
    - "For code modifications, use apply_patch with unified diff format including 3+ context lines."
    - "Chain multiple DIFFERENT tool calls without stopping to narrate between them."
  "gpt-4o*":
    - "For code modifications, use apply_patch with unified diff format including 3+ context lines."
    - "CRITICAL: Do NOT output tool call JSON in your response text. Use the tools API."
    - "Call tools directly without explanation — don't say 'I'll use X tool'."
    - "Avoid duplicate or redundant calls for the same operation."
    - "When a tool returns an error, ACKNOWLEDGE it. After 2 failures, STOP and report."
    - "CRITICAL: When a task requires multiple file operations, chain ALL tool calls consecutively. Do NOT stop to narrate after each tool call. After receiving a tool result, immediately make the next tool call."
    - "When asked to read multiple files, call read_file for EACH file before responding. Do NOT read one file then describe it."
  "gpt-5*":
    - "For code modifications, ALWAYS use apply_patch - do NOT use read_file when you should be editing."
    - "Include context lines (3+ before/after) in patches for reliable application."
    - "CRITICAL: Do NOT output tool call JSON like {\"tool\": \"...\", \"arguments\": {...}} in your response. Use the tools API for all tool calls."
    - "CRITICAL: When a tool returns an error, ACKNOWLEDGE it to the user. After 2 consecutive failures, STOP retrying and report the issue."
    - "Call tools directly - don't explain what you'll do first."
    - "Avoid duplicate tool calls. Chain multiple DIFFERENT tool calls without stopping to narrate."
    - "For large file writes: generate the COMPLETE file content - never truncate or abbreviate."
  "gpt-4.1*":
    - "You have 1M token context - leverage it for large codebase analysis."
    - "For code modifications, ALWAYS use apply_patch with unified diff format - do NOT use read_file for edits."
    - "Generate complete patches with ALL context lines (3+ before/after) - never output empty patches."
    - "CRITICAL: Do NOT output tool call JSON in your response text. Example of what NOT to do: {\"run_command\": {\"command\": \"pytest\"}}. Use the tools API instead."
    - "CRITICAL: When a tool returns an error, ACKNOWLEDGE the failure to the user. Do NOT silently retry."
    - "After 2 consecutive failures, STOP retrying and report what went wrong."
    - "Call tools directly without explanation - don't say 'I'll use X tool'."
    - "Avoid duplicate or redundant calls. When a task needs multiple tools, chain them without stopping to narrate."
    - "For large file writes (50+ lines): ensure COMPLETE content in the tool call - never truncate."
  "o4-mini*":
    - "Use your reasoning capabilities for complex tool calling decisions."
    - "For code modifications, use apply_patch with unified diff format."
    - "After reasoning, make a single precise tool call via the tools API."
    - "CRITICAL: Do NOT output tool call JSON in your response text - use the native tools API only."
    - "CRITICAL: When a tool fails, acknowledge the error to the user. Do NOT silently continue."
    - "Your response should contain your reasoning and conclusion - tool calls go through the API, not in text."
  "sonar*":
    - "You have real-time web access - use it for current information."
    - "Always cite sources with markdown links."
    - "CRITICAL: Do NOT make 5-6 duplicate apply_patch calls for the same file. One patch per file, but chain calls across DIFFERENT files."
    - "To call a tool, output ONLY the JSON object — example: {\"tool\": \"read_file\", \"arguments\": {\"filepath\": \"path\"}}. No surrounding text, no markdown fences."
    - "Keep apply_patch calls SMALL. Patch specific sections, NOT entire files. Large patches get truncated and fail."
    - "If a tool call was truncated, do NOT repeat it. Break the work into smaller patches or use a different tool."
    - "Do NOT mention tools in your response that you didn't actually call."
    - "After calling a tool, provide minimal response - let the tool output speak for itself."
  "gemini-3-flash*":
    - "You excel at code editing - use apply_patch confidently for all file modifications."
    - "Include all necessary imports and context in patches."
    - "Verify tool exists in available tools list before calling - don't hallucinate tool names."
    - "For file edits: apply_patch > write_file. Only use write_file for new files."
    - "IMPORTANT: Do NOT call apply_patch twice for the same file. Chain calls for DIFFERENT files without stopping."
    - "Let the patch contain all code changes - your response can briefly confirm the action taken."
    - "For complex patches (indentation, multiline): Include ALL affected lines with proper context (3+ lines before/after)."
    - "replace_block requires ALL 3 parameters: file_path, search, replace — NEVER omit search."
  "gemini-3.1-pro*customtools*":
    - "You are optimized for custom tool usage and agentic workflows - leverage this strength."
    - "Chain multiple DIFFERENT tool calls consecutively without stopping to narrate between them."
    - "For code modifications, ALWAYS use apply_patch with complete unified diffs (3+ context lines)."
    - "Call tools directly - do NOT explain what you'll do first."
    - "Do NOT output tool call JSON in your response text - use native tool calling only."
    - "Verify tool exists in available tools list before calling - don't hallucinate tool names."
    - "CRITICAL: When a tool returns an error or failure, FIRST acknowledge it in your response text. THEN investigate if needed. Do NOT silently call more tools without telling the user what failed."
    - "CRITICAL: After 2 failed attempts at the same operation (including sudo/alternative variants), STOP retrying. Tell the user the operation cannot be completed and explain why."
    - "CRITICAL: NEVER call the same tool with the same arguments twice. Use the result from the first call. If list_dir or read_file already returned data, use that data — do NOT re-read."
    - "When asked to run tests or commands, use run_command FIRST. Do NOT list or read test files — execute them."
    - "Write-test-fix cycle: after writing code, run tests. If tests fail, fix the code, then re-run tests. Do NOT rewrite the file multiple times without re-running tests between attempts."
  "gemini-3.1-pro*":
    - "You are an advanced reasoning model with 1M context - leverage it for complex multi-file analysis."
    - "For code modifications, ALWAYS use apply_patch with complete unified diffs (3+ context lines)."
    - "Focus on precise tool selection - use specialized tools like apply_patch over generic ones."
    - "Call tools directly without explanation - don't say 'I'll use X tool'."
    - "Do NOT output tool call JSON in your response text - use native tool calling only."
    - "Chain multiple DIFFERENT tool calls without stopping to narrate between them."
    - "When modifying code, always use apply_patch - never use read_file or write_file for edits."
    - "CRITICAL: When a tool returns an error or failure, ACKNOWLEDGE it in your response. Do NOT silently continue or claim success."
    - "CRITICAL: After 2 failed attempts (including sudo/alternative variants), STOP and report the issue."
    - "NEVER call the same tool with the same arguments twice — use the cached result and move on."
    - "When asked to run tests, use run_command directly. Do NOT read test files instead of executing them."
    - "Write-test-fix cycle: write code → run tests → if fail, fix → re-run tests. Always re-run tests after fixing."
  "gemini-2.5-flash*":
    - "CRITICAL: For file modifications, you MUST use apply_patch, not read_file or write_file."
    - "Generate patches immediately - don't explain what you'll do first, just call apply_patch."
    - "Include all affected lines in patches - incomplete patches will fail."
    - "Tool calling accuracy is critical - double-check you're using the right tool."
    - "CRITICAL: Do NOT output tool call JSON in your response text - severe anti-pattern detected."
    - "Do NOT mention tools in your response that you didn't call - hallucination detected."
    - "Do NOT make duplicate tool calls. Chain multiple DIFFERENT calls without stopping."
    - "Keep your response minimal when using tools - let the tool output speak for itself."
  "gemini-2.5-pro*":
    - "Focus on tool selection accuracy - prefer specialized tools like apply_patch over generic ones."
    - "For existing file modifications, apply_patch is mandatory - write_file is for new files only."
    - "Multi-tool sequences: plan the sequence, then execute each tool in order."
    - "Verify each tool call succeeded before proceeding to the next step."
---

## Project: ppxai

ppxai is a terminal-based UI application for interacting with multiple AI providers (Perplexity AI, OpenAI, Gemini, local models via Ollama/vLLM).

### Code Style

- Python 3.10+ with type hints
- Use dataclasses for data structures
- Async/await for I/O operations
- pytest for testing

### Architecture

- `ppxai/engine/` - Core business logic (no UI dependencies)
- `ppxai/engine/providers/` - Provider implementations:
  - `openai_native.py` - Native OpenAI (GPT-5.x, o-series, Codex via Responses API)
  - `gemini.py` - Native Gemini (google-genai SDK)
  - `openai_compat.py` - OpenAI-compatible (Perplexity, local/vLLM, custom)
- `ppxai/engine/model_profiles.py` - Per-model behavioral profiles (tool calling, API routing)
- `ppxai/engine/tools/` - Tool system with builtins + brace-counting JSON parser
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
- `docs/TODO-v1.16.1.md` - Current v1.16.1 task list (FileTree + TUI polish)
- `docs/KNOWN-ISSUES.md` - Known issues tracker (KI-001: google-genai SDK pin)

### Current Version: v1.16.1-dev

**v1.16.0 Features:**
- **NEW:** Profile-driven tool loop — `ToolCallingProfile.mode` replaces binary `native_tool_calling` decision
- **NEW:** Proper `tool` role messages — native mode uses `tool` role + `tool_call_id` instead of synthetic pairs
- **NEW:** Multi-tool support — all native tool calls processed per iteration (profile-gated)
- **NEW:** Agent UI noise reduction — `TOOL_GROUP_START/END` events, collapsible groups in all 4 clients
- **NEW:** Per-model `tool_calling` config overrides (3-layer: built-in → AGENTS.md → ppxai-config.json)
- **NEW:** `/model info` command — shows effective profile with source attribution
- **NEW:** `/ls` and `/tree` commands — directory listing in all 3 clients + HTTP endpoints
- **NEW:** Benchmark v2 — 36 tests across 9 categories, AGENTS.md delta testing, partial credit scoring
- **NEW:** `BaseProvider` ABC — all providers inherit shared interface, `hasattr` guards eliminated
- **FIX:** SSE event type dispatch — side-channel events emit correct EventType
- **FIX:** Consent deadlock — SSE generator uses racing poll pattern

**v1.15.6 Features:**
- **NEW:** Native OpenAI provider (`openai_native.py`) — Chat Completions + Responses API routing
- **NEW:** Model profile system — 37 built-in profiles for 27 models
- **NEW:** Brace-counting JSON parser — handles nested braces in apply_patch diffs

**v1.15.5 Features:**
- **CHANGE:** Multi-line chat input — Enter inserts newlines, Ctrl+Enter submits
- **FIX:** Escape key priority-based dismissal — help panel > modal screens > side panel
- **FIX:** PyInstaller build — added missing `blinker` hiddenimport for EventBus

**v1.15.4 Features:**
- **NEW:** `/preview` command — live-reloading HTML preview across TUI, Web App, VSCode
- **FIX:** Browser cache busting for CSS/JS/JSON assets in preview
- **FIX:** Corporate SSL support with `_create_ssl_context()` and HTTP fallback
