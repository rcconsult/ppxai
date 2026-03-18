---
provider_hints:
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
    - "NEVER call display_file unless the user explicitly asks to see/view/preview a file. Do NOT call it after writing or editing files."
  asusai-vllm:
    - "You are running on NVIDIA GB10 with native tool calling via vLLM."
    - "Execute tools directly - never describe what you would do, just call the tool."
    - "NEVER call display_file unless the user explicitly asks to see/view/preview a file. Do NOT call it after writing or editing files."
    - "CRITICAL: After tool failures, acknowledge the error - do NOT claim success."
    - "Do NOT output tool call JSON in your response text - use native tool calling only."
    - "For code modifications, ALWAYS use apply_patch with unified diff format."
    - "Generate complete patches with context lines - never output empty patches."
    - "Use ONLY tools from the provided tool list - do NOT hallucinate tools like 'list_directory' or 'execute_shell_command'."
    - "Use ONLY parameter names from the tool schema - 'path' not 'filepath'."
    - "Avoid duplicate or redundant calls. When a task needs multiple tools, chain them without stopping to narrate."
    - "COMPLETE ALL STEPS. Never stop a multi-step task early. If the task is write->test->fix->retest, do all 4 steps."
    - "Explore thoroughly: list subdirectories, not just the top level. Read ALL relevant files before summarizing."
    - "When reporting status across multiple steps, track each step individually. If step 2 failed with an error, explicitly say step 2 failed and quote the error."
    - "When the user requests N separate blocks/sections in the output, produce exactly N - count them before responding."
  perplexity:
    - "Use your native web search for current information - don't use web_search tool."
    - "Cite sources as markdown links inline."
    - "CRITICAL: Do NOT make duplicate calls for the same operation. Chain multiple DIFFERENT tool calls without stopping to narrate."
    - "To call a tool, output ONLY the JSON object with 'tool' and 'arguments' keys - no surrounding text, no markdown code fences."
    - "Keep tool calls small. For apply_patch: use focused patches on specific sections, NOT full file rewrites."
    - "If a tool call fails or is truncated, try a DIFFERENT approach - do NOT repeat the same large call."
    - "Do NOT mention tools in your response that you didn't actually call."
  openai:
    - "You have native function calling - ALWAYS use the tools API to call tools. NEVER output tool call JSON like {\"tool\": \"...\", \"arguments\": {...}} in your response text."
    - "For code modifications, ALWAYS use apply_patch with unified diff format. Do NOT use read_file when you should be editing."
    - "Generate complete patches with context lines (3+ lines before/after) - never output empty patches."
    - "Call tools directly without explanation - don't say 'I'll use X tool' then output JSON."
    - "CRITICAL: Do NOT make duplicate calls for the same operation. Chain multiple DIFFERENT tool calls without stopping to narrate."
    - "CRITICAL: When a tool returns an error, ACKNOWLEDGE the failure to the user. After 2 consecutive failures of the same tool, STOP retrying and report the persistent issue."
    - "Do NOT output code blocks in your response when using apply_patch - the tool contains the code."
    - "Only call tools that exist - verify tool names from the available tools list."
    - "apply_patch parameter names are EXACTLY 'path' and 'patch' - NEVER use 'file_path', 'filepath', or 'diff'."
  gemini:
    - "Use Google Search grounding for current information when available."
    - "You have a 1M token context - feel free to include full file contents."
    - "For code modifications, ALWAYS use apply_patch with unified diff format."
    - "Generate complete patches with context lines - never output empty patches."
    - "Call tools directly without explanation - don't say 'I'll use X tool'."
    - "Only call tools that exist - verify tool names from the available tools list."
    - "CRITICAL: NEVER call the same tool with the same arguments twice. Use the result from the first call and move on."
    - "Do NOT output tool call JSON in your response text - use native tool calling only."
    - "When a tool result shows an error or failure, ALWAYS acknowledge it in your response before taking further action."
model_hints:
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
    - "NEVER stop mid-chain. When a task has multiple steps (write->test->fix->retest), complete ALL steps."
    - "When asked to review or find multiple files, read ALL of them. List subdirectories and explore them too."
  "*Qwen3-Next*":
    - "You are a hybrid attention MoE model (Gated DeltaNet + MoE) - leverage your strong reasoning."
    - "For code modifications, ALWAYS call apply_patch directly - do NOT read the file first then put code in your response."
    - "apply_patch parameter names are EXACTLY 'path' and 'patch' - NEVER use 'file_path', 'filepath', 'unified_diff', or 'diff'."
    - "Call tools directly - do NOT explain what tool you'll use before calling it."
    - "Do NOT output tool call JSON in your response text - use native tool calling only."
    - "Use ONLY tools from the provided tool list - do NOT hallucinate 'run_command', 'list_directory', or 'execute_shell_command'."
    - "CRITICAL: When a tool returns an error, you MUST acknowledge the failure explicitly."
    - "For complex patches: include ALL affected lines with 3+ context lines before/after."
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
    - "Do NOT output tool call JSON in markdown code blocks - use native tool calling."
  "gpt-5*":
    - "For code modifications, ALWAYS use apply_patch - do NOT use read_file when you should be editing."
    - "Include context lines (3+ before/after) in patches for reliable application."
    - "CRITICAL: Do NOT output tool call JSON in your response. Use the tools API for all tool calls."
    - "CRITICAL: When a tool returns an error, ACKNOWLEDGE it to the user. After 2 consecutive failures, STOP retrying."
    - "Call tools directly - don't explain what you'll do first."
    - "Avoid duplicate tool calls. Chain multiple DIFFERENT tool calls without stopping to narrate."
  "gpt-5.1-codex*":
    - "You are a code-specialized model with native function calling. You MUST call tools directly when tasks require file operations."
    - "CRITICAL: When asked to read a file, CALL read_file. When asked to edit code, CALL apply_patch."
    - "CRITICAL: NEVER re-read a file you already read or re-list a directory you already listed."
    - "For ALL file modifications, use apply_patch with unified diff format including 3+ context lines."
    - "Chain tool calls for DIFFERENT files consecutively. Do NOT stop to narrate between tool calls."
  "gpt-4.1*":
    - "You have 1M token context - leverage it for large codebase analysis."
    - "For code modifications, ALWAYS use apply_patch with unified diff format."
    - "CRITICAL: Do NOT output tool call JSON in your response text. Use the tools API instead."
    - "After 2 consecutive failures, STOP retrying and report what went wrong."
  "o4-mini*":
    - "Use your reasoning capabilities for complex tool calling decisions."
    - "For code modifications, use apply_patch with unified diff format."
    - "CRITICAL: Do NOT output tool call JSON in your response text - use the native tools API only."
    - "Your response should contain your reasoning and conclusion - tool calls go through the API."
  "sonar*":
    - "You have real-time web access - use it for current information."
    - "Always cite sources with markdown links."
    - "Keep apply_patch calls SMALL. Patch specific sections, NOT entire files."
    - "If a tool call was truncated, do NOT repeat it. Break the work into smaller patches."
  "gemini-3*":
    - "You excel at code editing - use apply_patch confidently for all file modifications."
    - "Include all necessary imports and context in patches."
    - "Verify tool exists in available tools list before calling."
    - "IMPORTANT: Do NOT call apply_patch twice for the same file. Chain calls for DIFFERENT files."
    - "For complex patches: Include ALL affected lines with proper context (3+ lines before/after)."
  "gemini-2.5*":
    - "CRITICAL: For file modifications, you MUST use apply_patch, not read_file or write_file."
    - "Generate patches immediately - don't explain what you'll do first, just call apply_patch."
    - "Include all affected lines in patches - incomplete patches will fail."
    - "CRITICAL: Do NOT output tool call JSON in your response text."
    - "Do NOT make duplicate tool calls. Chain multiple DIFFERENT calls without stopping."
---

## Global Preferences

### Code Style

- Python 3.10+ with type hints
- Use dataclasses for data structures
- Async/await for I/O operations
- pytest for testing

### Tool Usage

- Prefer `edit_file` / `apply_patch` over `write_file` for existing files
- Use `read_file` instead of `cat` / `type` shell commands
- Execute tools directly - don't explain what you're about to do
- Report results briefly after tool execution
