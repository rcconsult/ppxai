"""
Tool manager for the ppxai engine.

Handles tool registration, filtering by provider, and execution.
"""

from typing import Dict, List, Optional, Any, Tuple
import json
import logging
from .base import BaseTool, FunctionTool
from ..types import Event, EventType, ToolCallInfo
from ...config import get_tool_description_overrides
from .wrappers import get_registry as get_wrapper_registry

logger = logging.getLogger(__name__)


class ToolManager:
    """Manages tool registration and execution.

    Tools are provider-aware and filtered based on current provider's capabilities.
    """

    def __init__(self):
        """Initialize the tool manager."""
        self._tools: Dict[str, BaseTool] = {}
        self._provider: Optional[str] = None
        self._model: Optional[str] = None  # Track model for description overrides
        self._description_overrides: Dict[str, str] = {}  # Cached description overrides
        self.max_iterations: int = 15
        self.auto_retry_empty: int = 3  # Max retries for empty responses (0=disabled)
        # Loop detection - prevent models from calling same tool with same args repeatedly
        self.max_same_tool_calls: int = 3  # Max consecutive calls to same tool+args (0=disabled)
        self._tool_call_history: List[Tuple[str, str]] = []  # Track (tool_name, args_hash) for loop detection

        # Display limit configuration (v1.15.3)
        # Controls how much of a tool result is displayed to the user
        # (Full result is always sent to the LLM regardless of display limit)
        self.default_display_limit: int = 2000

        # Tool-specific display limits
        self.tool_display_limits: Dict[str, Any] = {
            # Weather tool has format-specific limits
            "get_weather": {
                "short": 500,      # One-line format: "Geneva: ☁️  +5°C"
                "detailed": 1500,  # Current weather with details
                "forecast": 5000,  # Full 2-day forecast (4300 chars typical)
                "default": 2000
            },
            # Other tools with custom limits
            "fetch_url": 5000,  # Web pages can be long
            "web_search": 3000,  # Search results with multiple entries
            "list_directory": 3000,  # Large directories
            "read_file": 10000,  # Code files can be long
        }

    def register_tool(self, tool: BaseTool):
        """Register a tool.

        Args:
            tool: Tool instance to register
        """
        self._tools[tool.name] = tool

    def register_function(
        self,
        name: str,
        description: str,
        parameters: Dict[str, Any],
        handler: callable,
        provider_specific: Optional[List[str]] = None,
        provider_excluded: Optional[List[str]] = None
    ):
        """Register a function as a tool.

        Args:
            name: Tool name
            description: Tool description
            parameters: JSON Schema for parameters
            handler: Function to execute
            provider_specific: Only for these providers
            provider_excluded: Excluded for these providers
        """
        tool = FunctionTool(
            name=name,
            description=description,
            parameters=parameters,
            handler=handler,
            provider_specific=provider_specific,
            provider_excluded=provider_excluded
        )
        self.register_tool(tool)

    def set_provider(self, provider: str):
        """Set current provider (filters available tools).

        Args:
            provider: Provider name
        """
        self._provider = provider
        self._update_description_overrides()

    def set_model(self, model: str):
        """Set current model (for description overrides).

        v1.13.10: Different models may benefit from different tool descriptions.
        Small models often work better with minimal descriptions.

        Args:
            model: Model name (e.g., 'qwen2.5-coder:0.5b')
        """
        self._model = model
        self._update_description_overrides()

    def _update_description_overrides(self):
        """Refresh description overrides from config based on current provider/model."""
        self._description_overrides = get_tool_description_overrides(
            provider=self._provider,
            model=self._model
        )

    def _get_tool_description(self, tool: BaseTool) -> str:
        """Get tool description, applying any config overrides.

        v1.13.10: Allows per-provider/model description customization.

        Args:
            tool: Tool to get description for

        Returns:
            Tool description (override if configured, otherwise default)
        """
        return self._description_overrides.get(tool.name, tool.description)

    def get_tool_display_limit(self, tool_name: str, tool_args: Optional[Dict[str, Any]] = None) -> int:
        """Get display limit for a specific tool result.

        v1.15.3: Configurable, format-aware display limits for tool results.
        Full result is always sent to LLM; this only affects user display.

        Args:
            tool_name: Name of the tool
            tool_args: Tool arguments (used for format-specific limits)

        Returns:
            Character limit for displaying tool result to user
        """
        # Check if tool has specific configuration
        tool_config = self.tool_display_limits.get(tool_name)

        if tool_config is None:
            # No specific config, use default
            return self.default_display_limit

        # If config is a dict (format-specific), extract based on arguments
        if isinstance(tool_config, dict):
            # For get_weather, check the format parameter
            if tool_name == "get_weather" and tool_args:
                format_param = tool_args.get("format", "default")
                return tool_config.get(format_param, tool_config.get("default", self.default_display_limit))
            # For other dict-based configs, use default key
            return tool_config.get("default", self.default_display_limit)

        # Direct integer limit
        return tool_config

    def get_tool(self, name: str) -> Optional[BaseTool]:
        """Get a specific tool by name.

        Args:
            name: Tool name

        Returns:
            Tool if found and available, None otherwise
        """
        tool = self._tools.get(name)
        if tool is None:
            return None
        if self._provider and not tool.is_available_for(self._provider):
            return None
        return tool

    def get_available_tools(self) -> List[BaseTool]:
        """Get tools available for current provider.

        Returns:
            List of available tools
        """
        if self._provider is None:
            return list(self._tools.values())
        return [t for t in self._tools.values() if t.is_available_for(self._provider)]

    def list_tools(self) -> List[Dict[str, Any]]:
        """List available tools as dictionaries.

        Returns:
            List of tool info dicts with name, description, and source
        """
        return [
            {"name": t.name, "description": self._get_tool_description(t), "source": "engine"}
            for t in self.get_available_tools()
        ]

    def get_tools_openai_format(self) -> List[Dict[str, Any]]:
        """Get tools in OpenAI function calling format.

        This format is used by vLLM with --enable-auto-tool-choice and other
        OpenAI-compatible endpoints that support native tool calling.

        v1.13.10: Uses description overrides from config if configured.

        Returns:
            List of tool definitions in OpenAI format:
            [{"type": "function", "function": {"name": ..., "description": ..., "parameters": ...}}]
        """
        tools = self.get_available_tools()
        return [
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": self._get_tool_description(tool),
                    "parameters": tool.parameters,
                }
            }
            for tool in tools
        ]

    # Parameter alias groups: variations that should be treated as equivalent
    # Some models (e.g., GPT-OSS 120B via vLLM) use different parameter names
    # Each group contains variations that mean the same thing
    PARAM_ALIAS_GROUPS = [
        # File path variations (read_file uses 'filepath', editor tools use 'file_path')
        {"filepath", "file_path", "filePath", "file"},
        # Directory/path variations (set_working_directory uses 'path', search uses 'directory')
        {"path", "directory", "dir_path", "dirPath", "dir", "folder"},
        # Command variations (shell tool uses 'command')
        {"command", "cmd", "shell_command"},
        # Query variations (web_search uses 'query')
        {"query", "query_text", "search_query"},
        # Diff/patch variations (apply_patch uses 'unified_diff')
        {"unified_diff", "diff", "patch"},
        # URL variations (fetch_url uses 'url')
        {"url", "link", "webpage", "uri"},
        # Location variations (get_weather uses 'location')
        {"location", "city", "place"},
        # Container variations (container tools use 'container')
        {"container", "container_id", "container_name"},
        # Pod variations (kubernetes tools use 'pod')
        {"pod", "pod_name", "pod_id"},
        # Text/content variations (insert_text uses 'text')
        {"text", "content", "body"},
        # Search/replace variations (replace_block uses 'search' and 'replace')
        {"search", "find", "old_text", "original"},
        {"replace", "replacement", "new_text"},
    ]

    def _normalize_params(self, tool: BaseTool, kwargs: dict) -> dict:
        """Normalize parameter names to match tool's expected names.

        v1.13.9: Different tools use different naming conventions:
        - read_file uses 'filepath' (no underscore)
        - apply_patch uses 'file_path' (with underscore)

        This method maps model-provided parameter names to what the tool expects.

        Args:
            tool: The tool being called
            kwargs: Parameters provided by the model

        Returns:
            Parameters with names normalized to tool's expectations
        """
        tool_params = set(tool.parameters.get("properties", {}).keys())

        for alias_group in self.PARAM_ALIAS_GROUPS:
            # Find which canonical name the tool expects from this group
            expected = alias_group & tool_params
            if not expected:
                continue
            canonical = next(iter(expected))

            # Find if model provided any alias from this group
            provided = alias_group & set(kwargs.keys())
            if not provided:
                continue

            # If canonical already exists, just remove any duplicate aliases
            # (model may send both 'file_path' and 'filepath' in same call)
            if canonical in kwargs:
                for alias in provided:
                    if alias != canonical and alias in kwargs:
                        del kwargs[alias]
                continue

            # Map the provided alias to the canonical name and remove others
            alias = next(iter(provided))
            kwargs[canonical] = kwargs.pop(alias)
            # Remove any remaining aliases from this group
            for other_alias in provided:
                if other_alias != alias and other_alias in kwargs:
                    del kwargs[other_alias]

        return kwargs

    async def execute_tool(self, name: str, **kwargs) -> str:
        """Execute a tool by name.

        Args:
            name: Tool name
            **kwargs: Tool arguments

        Returns:
            Tool result as string

        Raises:
            ValueError: If tool not found or not available, or missing required arguments
        """
        tool = self.get_tool(name)
        if not tool:
            raise ValueError(f"Tool not found or not available: {name}")

        # Normalize parameter names to match tool's expectations
        # Some models use file_path, others use filepath - map to what tool expects
        kwargs = self._normalize_params(tool, kwargs)

        # Validate required arguments before execution
        # Some models (e.g., GPT-OSS 120B via vLLM) sometimes send empty arguments
        required = tool.parameters.get("required", [])
        missing = [arg for arg in required if arg not in kwargs]
        if missing:
            raise ValueError(f"Missing required arguments for {name}: {', '.join(missing)}")

        # Filter out unexpected parameters that model might hallucinate
        # Small models sometimes add parameters that don't exist in the tool schema
        tool_params = set(tool.parameters.get("properties", {}).keys())
        unexpected = [k for k in kwargs if k not in tool_params]
        for param in unexpected:
            del kwargs[param]

        return await tool.execute(**kwargs)

    def get_tools_prompt(self, working_dir: Optional[str] = None) -> str:
        """Generate system prompt describing available tools.

        Args:
            working_dir: Current working directory to include in prompt (v1.15.2)

        Returns:
            System prompt text for tool usage
        """
        tools = self.get_available_tools()
        if not tools:
            return ""

        prompt = "# IMPORTANT: You Have Access to Tools\n\n"

        # Include current working directory if available (v1.15.2)
        # This ensures LLM knows the current directory even after /cd commands.
        # v1.18.4 strengthening: the previous wording ("do NOT rely on
        # previous tool results") was insufficient — models were observed
        # confabulating paths from earlier conversation turns even when the
        # cwd above was correct. The fortified instruction below tells the
        # model the cwd is the SOLE source of truth and that tool outputs
        # from earlier turns may have run in a different directory.
        if working_dir:
            prompt += f"**Current Working Directory:** `{working_dir}`\n"
            prompt += "All relative paths in tool calls are resolved against this directory.\n"
            prompt += (
                "**This cwd is the ONLY source of truth for your current location.** "
                "Tool results earlier in this conversation may have run in a different "
                "directory (the user can `/cd` between turns). When summarizing tool "
                "output that references a path or directory, verify against the cwd "
                "above before quoting any other path. If a tool's output starts with "
                "a header like `Listing of /path/to/dir:` or `[cwd: /path/to/dir]`, "
                "quote that path verbatim — do not substitute a path from memory.\n\n"
            )

        prompt += "You MUST use these tools when the user asks for information you don't have access to natively.\n"
        prompt += "You are an AI assistant with tool capabilities. You have access to the user's filesystem, can run commands, search the web, and more. Use the tools proactively - don't ask the user for information you can get yourself!\n\n"

        # v1.18.5: append per-wrapper prompt blocks. The registry composes
        # blocks from all active wrappers (those with their binary on PATH,
        # not opted out) under a single header. Wrappers without prompt
        # blocks contribute nothing. Failures fall back silently.
        try:
            wrapper_blocks = get_wrapper_registry().compose_prompt_blocks()
            if wrapper_blocks:
                prompt += "## Shell wrapper context\n\n"
                prompt += wrapper_blocks + "\n\n"
        except Exception as e:
            logger.debug("Wrapper prompt-block composition skipped: %s", e)

        prompt += "## How to Call a Tool\n\n"
        prompt += "To use a tool, respond ONLY with a JSON code block in this exact format:\n\n"
        prompt += "```json\n{\n  \"tool\": \"tool_name\",\n  \"arguments\": {\"param\": \"value\"}\n}\n```\n\n"
        prompt += "## Available Tools:\n\n"

        for tool in tools:
            prompt += f"### {tool.name}\n"
            prompt += f"{self._get_tool_description(tool)}\n"
            if tool.parameters.get("properties"):
                prompt += "Parameters:\n"
                for param, info in tool.parameters["properties"].items():
                    required = "required" if param in tool.parameters.get("required", []) else "optional"
                    prompt += f"  - `{param}` ({required}): {info.get('description', '')}\n"
            prompt += "\n"

        prompt += "## CRITICAL INSTRUCTIONS:\n\n"

        # Build dynamic instructions based on available tools
        available_tool_names = {t.name for t in tools}
        instruction_num = 1

        if "get_datetime" in available_tool_names:
            prompt += f"{instruction_num}. **For date/time questions**: ALWAYS use the `get_datetime` tool. Do NOT say you don't have access.\n"
            instruction_num += 1

        if "get_weather" in available_tool_names:
            prompt += f"{instruction_num}. **For weather questions**: ALWAYS use the `get_weather` tool. Do NOT say you can't access weather.\n"
            instruction_num += 1

        if "web_search" in available_tool_names:
            prompt += f"{instruction_num}. **For web searches**: Use the `web_search` tool to find current information.\n"
            instruction_num += 1

        if "fetch_url" in available_tool_names:
            prompt += f"{instruction_num}. **For reading web pages**: Use the `fetch_url` tool to read URL contents.\n"
            instruction_num += 1

        # Filesystem tools
        if "list_directory" in available_tool_names or "read_file" in available_tool_names:
            prompt += f"{instruction_num}. **For exploring the user's project**: Use `list_directory` to see files, `read_file` to read contents. You CAN access the filesystem - use it!\n"
            instruction_num += 1

        if "execute_shell_command" in available_tool_names:
            prompt += f"{instruction_num}. **For system operations**: Use the `execute_shell_command` tool to run commands, create directories, file operations, etc.\n"
            instruction_num += 1

        prompt += f"{instruction_num}. When calling a tool, output ONLY the JSON block, nothing else.\n"
        instruction_num += 1
        prompt += f"{instruction_num}. **COMPLETE ALL STEPS**: If the user asks for multiple actions (e.g., 'run X and then verify Y'), you MUST complete ALL steps before responding. Do not stop after the first step - continue using tools until every part of the request is done.\n"
        instruction_num += 1
        prompt += f"{instruction_num}. After receiving tool results, ask yourself: 'Did I complete everything the user asked?' If not, call another tool. Only respond when ALL parts are done.\n"
        instruction_num += 1
        prompt += f"{instruction_num}. NEVER say 'I don't have access to real-time data' or 'I can't execute commands' - you DO have access via these tools!\n"
        instruction_num += 1
        prompt += f"{instruction_num}. Don't pass unnecessary parameters - use tool defaults (e.g., don't specify max_lines unless you need a specific limit).\n"
        instruction_num += 1

        # v1.15.2: Add critical instructions to prevent hallucination and tool avoidance
        prompt += "\n## CRITICAL: Tool Result Validation\n\n"
        prompt += f"{instruction_num}. **ALWAYS check tool results before claiming success**. If a tool returns 'Error:', 'not found', or 'failed', you MUST acknowledge the failure - do NOT claim success.\n"
        instruction_num += 1
        prompt += f"{instruction_num}. **NEVER claim to have created/written/opened a file unless a tool result confirms it**. Describing what you would write is NOT the same as actually writing it.\n"
        instruction_num += 1
        prompt += f"{instruction_num}. **If the user asks you to 'display' or 'show' a file, you MUST call the display_file tool**. Do NOT just describe the file contents.\n"
        instruction_num += 1
        # Gate the shell instruction on the shell tool actually being
        # available — same pattern as the execute_shell_command block above
        # (~L436). Without this, a tool set that excludes shell (e.g. a
        # capability-scoped agent run granting only read_file) still tells the
        # model to "use execute_shell_command", naming an off-grant tool.
        if "execute_shell_command" in available_tool_names:
            prompt += f"{instruction_num}. **If the user gives a shell command (like 'ls', 'dir', 'cat'), you MUST use execute_shell_command**. Do NOT fabricate the output.\n"
            instruction_num += 1
        prompt += f"{instruction_num}. **Call tools directly - do NOT output tool JSON in your response text**. When you want to use a tool, make the tool call immediately.\n"

        return prompt

    def clear(self):
        """Remove all registered tools."""
        self._tools.clear()

    # === Loop Detection (v1.13.10) ===

    def reset_tool_history(self):
        """Reset tool call history for a new chat turn.

        Should be called at the start of each chat() invocation.
        """
        self._tool_call_history.clear()

    def _hash_args(self, args: Dict[str, Any]) -> str:
        """Create a stable hash of tool arguments for loop detection.

        Args:
            args: Tool arguments dict

        Returns:
            JSON string representation of sorted args (for comparison)
        """
        try:
            return json.dumps(args, sort_keys=True, default=str)
        except (TypeError, ValueError):
            return str(args)

    def record_tool_call(self, tool_name: str, args: Optional[Dict[str, Any]] = None):
        """Record a tool call for loop detection.

        Args:
            tool_name: Name of the tool being called
            args: Tool arguments (optional, for argument-aware loop detection)
        """
        args_hash = self._hash_args(args or {})
        self._tool_call_history.append((tool_name, args_hash))

    def is_tool_loop_detected(self, tool_name: str, args: Optional[Dict[str, Any]] = None) -> bool:
        """Check if calling this tool with these args would create a loop.

        A loop is detected when the same tool with the same arguments has been
        called max_same_tool_calls times consecutively. Calling the same tool
        with different arguments (e.g., list_directory on different paths) is
        allowed and does not trigger loop detection.

        Args:
            tool_name: Name of the tool about to be called
            args: Tool arguments (optional)

        Returns:
            True if this call would exceed the loop threshold
        """
        if self.max_same_tool_calls <= 0:
            return False  # Loop detection disabled

        args_hash = self._hash_args(args or {})

        # Count consecutive calls to this tool with same args from the end of history
        consecutive = 0
        for prev_tool, prev_args_hash in reversed(self._tool_call_history):
            if prev_tool == tool_name and prev_args_hash == args_hash:
                consecutive += 1
            else:
                break

        # Would this call exceed the threshold?
        return consecutive >= self.max_same_tool_calls

    def get_loop_message(self, tool_name: str) -> str:
        """Get a message to inject when a loop is detected.

        Args:
            tool_name: Tool that was being called repeatedly

        Returns:
            Message prompting the model to synthesize instead of loop
        """
        return (
            f"You have called the '{tool_name}' tool with the same arguments {self.max_same_tool_calls} times consecutively. "
            "Please stop calling tools and provide a response based on the results you already have. "
            "Synthesize the information into a helpful answer for the user."
        )

    async def cleanup(self):
        """Clean up resources (for MCP tools, etc)."""
        # Placeholder for future MCP cleanup
        pass
