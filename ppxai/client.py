"""
API client for interacting with LLM providers (Perplexity AI or custom self-hosted models).
"""

import json
import os
import httpx
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, List

from openai import OpenAI
from rich.console import Console
from rich.markdown import Markdown

from .config import (
    SESSIONS_DIR,
    EXPORTS_DIR,
    USAGE_FILE,
    MODEL_PRICING,
    MODEL_PROVIDER,
    get_provider_config,
    get_active_pricing,
    get_provider_capabilities,
)
from .engine.context import ContextInjector

# Initialize Rich console
console = Console()


class AIClient:
    """Client for interacting with LLM APIs (Perplexity or custom self-hosted)."""

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.perplexity.ai",
        session_name: Optional[str] = None,
        provider: Optional[str] = None
    ):
        """
        Initialize the AI client.

        Args:
            api_key: API key for authentication
            base_url: Base URL for the API endpoint
            session_name: Optional session name for conversation tracking
            provider: Provider name (perplexity, custom) for pricing lookup
        """
        # Check if SSL verification should be disabled
        # Use SSL_VERIFY environment variable (applies to all HTTPS connections)
        ssl_verify = os.getenv("SSL_VERIFY", "true").lower() != "false"

        if not ssl_verify:
            # Create custom httpx client with SSL verification disabled
            http_client = httpx.Client(verify=False)
            self.client = OpenAI(
                api_key=api_key,
                base_url=base_url,
                http_client=http_client
            )
        else:
            self.client = OpenAI(
                api_key=api_key,
                base_url=base_url
            )
        self.base_url = base_url
        self.provider = provider or MODEL_PROVIDER
        self.conversation_history = []
        self.session_name = session_name or f"session_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        self.session_metadata = {
            "created_at": datetime.now().isoformat(),
            "model": None,
            "provider": self.provider,
            "message_count": 0
        }
        self.current_session_usage = {
            "total_tokens": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "estimated_cost": 0.0
        }
        self.auto_route = True  # Auto-route coding tasks to best model
        self.auto_inject_context = True  # Auto-inject file contents
        self.context_injector = ContextInjector(os.getcwd())

    def chat(self, message: str, model: str, stream: bool = True):
        """
        Send a chat message to the LLM API.

        Args:
            message: The user's message
            model: The model ID to use
            stream: Whether to stream the response

        Returns:
            The assistant's response
        """
        # Auto-inject file context if enabled
        enhanced_message = message
        if self.auto_inject_context:
            enhanced_message, injected = self.context_injector.inject_context(message)
            if injected:
                for ctx in injected:
                    size_str = self.context_injector._format_size(ctx.size)
                    truncation_note = " (truncated)" if ctx.truncated else ""
                    console.print(f"[cyan]📎 Attached:[/cyan] {ctx.source} ({size_str}){truncation_note}")

        self.conversation_history.append({
            "role": "user",
            "content": enhanced_message
        })

        # Build messages list, adding citation prompt if provider has web search/citations
        messages = self.conversation_history.copy()
        capabilities = get_provider_capabilities(self.provider)
        if capabilities.get("citations") or capabilities.get("web_search"):
            # Add system prompt for inline citation URLs (prepend to messages)
            citation_system = {
                "role": "system",
                "content": (
                    "When citing sources, always include the full URL in parentheses after "
                    "the citation number, like [1](https://example.com). This helps users "
                    "click through to the sources directly."
                )
            }
            messages = [citation_system] + messages

        try:
            if stream:
                return self._stream_response(model, messages)
            else:
                return self._get_response(model, messages)
        except Exception as e:
            console.print(f"[red]Error: {str(e)}[/red]")
            self.conversation_history.pop()  # Remove the failed message
            return None

    def _stream_response(self, model: str, messages: list):
        """Stream the response from the API."""
        import time
        start_time = time.time()

        response_chunks = []
        citations = []
        last_chunk = None

        response_stream = self.client.chat.completions.create(
            model=model,
            messages=messages,
            stream=True
        )

        console.print("\n[bold cyan]Assistant:[/bold cyan] [dim](streaming...)[/dim]")
        for chunk in response_stream:
            last_chunk = chunk

            if chunk.choices[0].delta.content:
                content = chunk.choices[0].delta.content
                response_chunks.append(content)
                # Show a simple progress indicator instead of raw text
                console.print(".", end="", style="dim")

            # Try to capture citations from various possible locations
            if hasattr(chunk, 'citations') and chunk.citations:
                citations = chunk.citations
            elif hasattr(chunk.choices[0], 'citations') and chunk.choices[0].citations:
                citations = chunk.choices[0].citations
            elif hasattr(chunk.choices[0].delta, 'citations') and chunk.choices[0].delta.citations:
                citations = chunk.choices[0].delta.citations

        # Clear the progress dots and render the complete markdown
        console.print("\n")

        full_response = "".join(response_chunks)

        # Render the response as formatted markdown
        if full_response.strip():
            console.print(Markdown(full_response))

        self.conversation_history.append({
            "role": "assistant",
            "content": full_response
        })

        # Track usage from the last chunk
        if last_chunk and hasattr(last_chunk, 'usage') and last_chunk.usage:
            self._track_usage(last_chunk.usage, model)

        # Display citations if available
        if citations:
            self._display_citations(citations)

        # Show response time
        elapsed = time.time() - start_time
        console.print(f"[dim]({elapsed:.1f}s)[/dim]\n")

        return full_response

    def _get_response(self, model: str, messages: list):
        """Get a non-streaming response from the API."""
        import time
        start_time = time.time()

        response = self.client.chat.completions.create(
            model=model,
            messages=messages,
            stream=False
        )

        assistant_message = response.choices[0].message.content

        # Render the response as formatted markdown
        console.print("\n[bold cyan]Assistant:[/bold cyan]")
        if assistant_message.strip():
            console.print(Markdown(assistant_message))
        console.print()

        self.conversation_history.append({
            "role": "assistant",
            "content": assistant_message
        })

        # Track usage
        if hasattr(response, 'usage') and response.usage:
            self._track_usage(response.usage, model)

        # Display citations if available
        if hasattr(response, 'citations') and response.citations:
            self._display_citations(response.citations)

        # Show response time
        elapsed = time.time() - start_time
        console.print(f"[dim]({elapsed:.1f}s)[/dim]\n")

        return assistant_message

    def _display_citations(self, citations):
        """Display citations as clickable links."""
        if not citations:
            return

        console.print("\n[bold yellow]Sources:[/bold yellow]")
        for idx, citation in enumerate(citations, 1):
            # Create clickable link using Rich's link markup
            clickable_link = f"[link={citation}]{citation}[/link]"
            console.print(f"[cyan]{idx}.[/cyan] {clickable_link}")
        console.print()

    def clear_history(self):
        """Clear the conversation history."""
        self.conversation_history = []

    def _track_usage(self, usage, model: str):
        """Track token usage and estimate costs."""
        prompt_tokens = getattr(usage, 'prompt_tokens', 0)
        completion_tokens = getattr(usage, 'completion_tokens', 0)
        total_tokens = getattr(usage, 'total_tokens', 0) or (prompt_tokens + completion_tokens)

        # Update current session usage
        self.current_session_usage["prompt_tokens"] += prompt_tokens
        self.current_session_usage["completion_tokens"] += completion_tokens
        self.current_session_usage["total_tokens"] += total_tokens

        # Calculate cost using provider-specific pricing
        pricing_table = get_active_pricing()
        if model in pricing_table:
            pricing = pricing_table[model]
            input_cost = (prompt_tokens / 1_000_000) * pricing["input"]
            output_cost = (completion_tokens / 1_000_000) * pricing["output"]
            total_cost = input_cost + output_cost
            self.current_session_usage["estimated_cost"] += total_cost

        # Update global usage stats
        self._update_global_usage(model, prompt_tokens, completion_tokens, total_tokens)

    def _update_global_usage(self, model: str, prompt_tokens: int, completion_tokens: int, total_tokens: int):
        """Update the global usage statistics file."""
        usage_data = {}
        if USAGE_FILE.exists():
            with open(USAGE_FILE, 'r') as f:
                usage_data = json.load(f)

        today = datetime.now().strftime('%Y-%m-%d')
        if today not in usage_data:
            usage_data[today] = {}

        if model not in usage_data[today]:
            usage_data[today][model] = {
                "requests": 0,
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0
            }

        usage_data[today][model]["requests"] += 1
        usage_data[today][model]["prompt_tokens"] += prompt_tokens
        usage_data[today][model]["completion_tokens"] += completion_tokens
        usage_data[today][model]["total_tokens"] += total_tokens

        with open(USAGE_FILE, 'w') as f:
            json.dump(usage_data, f, indent=2)

    def get_usage_summary(self) -> Dict:
        """Get current session usage summary."""
        return self.current_session_usage.copy()

    def export_conversation(self, filename: Optional[str] = None) -> Path:
        """Export conversation to a markdown file."""
        if not filename:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f"conversation_{timestamp}.md"

        filepath = EXPORTS_DIR / filename

        # Build markdown content
        content = f"# Conversation Export\n\n"
        content += f"**Exported:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        content += f"**Session:** {self.session_name}\n"
        if self.session_metadata.get("model"):
            content += f"**Model:** {self.session_metadata['model']}\n"
        content += f"**Messages:** {len(self.conversation_history)}\n\n"

        # Add usage stats
        usage = self.get_usage_summary()
        content += f"## Usage Statistics\n\n"
        content += f"- Total Tokens: {usage['total_tokens']:,}\n"
        content += f"- Prompt Tokens: {usage['prompt_tokens']:,}\n"
        content += f"- Completion Tokens: {usage['completion_tokens']:,}\n"
        content += f"- Estimated Cost: ${usage['estimated_cost']:.4f}\n\n"

        content += "---\n\n"

        # Add conversation
        content += "## Conversation\n\n"
        for msg in self.conversation_history:
            role = msg['role'].capitalize()
            content_text = msg['content']
            content += f"### {role}\n\n{content_text}\n\n"

        # Write to file
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)

        return filepath

    def save_session(self) -> Path:
        """Save current session to a JSON file."""
        filepath = SESSIONS_DIR / f"{self.session_name}.json"

        session_data = {
            "session_name": self.session_name,
            "metadata": self.session_metadata,
            "conversation_history": self.conversation_history,
            "usage": self.current_session_usage,
            "saved_at": datetime.now().isoformat()
        }

        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(session_data, f, indent=2)

        return filepath

    @staticmethod
    def load_session(
        session_name: str,
        api_key: str,
        base_url: str = "https://api.perplexity.ai",
        provider: str = None
    ) -> Optional['AIClient']:
        """Load a saved session."""
        filepath = SESSIONS_DIR / f"{session_name}.json"

        if not filepath.exists():
            return None

        with open(filepath, 'r', encoding='utf-8') as f:
            session_data = json.load(f)

        client = AIClient(api_key, base_url, session_name, provider)
        client.conversation_history = session_data.get("conversation_history", [])
        client.session_metadata = session_data.get("metadata", {})
        client.current_session_usage = session_data.get("usage", {
            "total_tokens": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "estimated_cost": 0.0
        })

        return client

    @staticmethod
    def list_sessions() -> List[Dict]:
        """List all saved sessions."""
        sessions = []
        for filepath in SESSIONS_DIR.glob("*.json"):
            try:
                with open(filepath, 'r') as f:
                    data = json.load(f)
                    sessions.append({
                        "name": data.get("session_name", filepath.stem),
                        "created_at": data.get("metadata", {}).get("created_at", "Unknown"),
                        "saved_at": data.get("saved_at", "Unknown"),
                        "message_count": len(data.get("conversation_history", []))
                    })
            except Exception:
                continue

        return sorted(sessions, key=lambda x: x.get("saved_at", ""), reverse=True)


# Backward compatibility alias
PerplexityClient = AIClient
