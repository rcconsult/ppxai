#!/usr/bin/env python3
"""
Perplexity AI Text UI Application
A terminal-based interface for interacting with Perplexity AI models.
"""

import os
import sys
import json
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, List
from openai import OpenAI
from rich.console import Console
from rich.panel import Panel
from rich.markdown import Markdown
from rich.prompt import Prompt
from rich.table import Table
from prompt_toolkit import prompt
from prompt_toolkit.history import InMemoryHistory
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Initialize Rich console
console = Console()

# Directories for data storage
SESSIONS_DIR = Path.home() / ".ppxai" / "sessions"
EXPORTS_DIR = Path.home() / ".ppxai" / "exports"
USAGE_FILE = Path.home() / ".ppxai" / "usage.json"

# Ensure directories exist
SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
EXPORTS_DIR.mkdir(parents=True, exist_ok=True)

# Perplexity API pricing (per million tokens) - approximate values
# Source: https://docs.perplexity.ai/guides/pricing
MODEL_PRICING = {
    "sonar": {"input": 0.20, "output": 0.20},
    "sonar-pro": {"input": 3.00, "output": 15.00},
    "sonar-reasoning": {"input": 1.00, "output": 5.00},
    "sonar-reasoning-pro": {"input": 5.00, "output": 15.00},
    "sonar-deep-research": {"input": 5.00, "output": 15.00},
}

# Available Perplexity models
MODELS = {
    "1": {
        "id": "sonar",
        "name": "Sonar",
        "description": "Lightweight search model with real-time grounding"
    },
    "2": {
        "id": "sonar-pro",
        "name": "Sonar Pro",
        "description": "Advanced search model for complex queries"
    },
    "3": {
        "id": "sonar-reasoning",
        "name": "Sonar Reasoning",
        "description": "Fast reasoning model for problem-solving with search"
    },
    "4": {
        "id": "sonar-reasoning-pro",
        "name": "Sonar Reasoning Pro",
        "description": "Precision reasoning with Chain of Thought capabilities"
    },
    "5": {
        "id": "sonar-deep-research",
        "name": "Sonar Deep Research",
        "description": "Exhaustive research with comprehensive reports"
    },
}


class PerplexityClient:
    """Client for interacting with Perplexity API."""

    def __init__(self, api_key: str, session_name: Optional[str] = None):
        """Initialize the Perplexity client."""
        self.client = OpenAI(
            api_key=api_key,
            base_url="https://api.perplexity.ai"
        )
        self.conversation_history = []
        self.session_name = session_name or f"session_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        self.session_metadata = {
            "created_at": datetime.now().isoformat(),
            "model": None,
            "message_count": 0
        }
        self.current_session_usage = {
            "total_tokens": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "estimated_cost": 0.0
        }

    def chat(self, message: str, model: str, stream: bool = True):
        """
        Send a chat message to Perplexity API.

        Args:
            message: The user's message
            model: The model ID to use
            stream: Whether to stream the response

        Returns:
            The assistant's response
        """
        self.conversation_history.append({
            "role": "user",
            "content": message
        })

        try:
            if stream:
                return self._stream_response(model)
            else:
                return self._get_response(model)
        except Exception as e:
            console.print(f"[red]Error: {str(e)}[/red]")
            self.conversation_history.pop()  # Remove the failed message
            return None

    def _stream_response(self, model: str):
        """Stream the response from the API."""
        response_chunks = []
        citations = []
        last_chunk = None

        response_stream = self.client.chat.completions.create(
            model=model,
            messages=self.conversation_history,
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

        return full_response

    def _get_response(self, model: str):
        """Get a non-streaming response from the API."""
        response = self.client.chat.completions.create(
            model=model,
            messages=self.conversation_history,
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

        # Calculate cost
        if model in MODEL_PRICING:
            pricing = MODEL_PRICING[model]
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
    def load_session(session_name: str, api_key: str) -> Optional['PerplexityClient']:
        """Load a saved session."""
        filepath = SESSIONS_DIR / f"{session_name}.json"

        if not filepath.exists():
            return None

        with open(filepath, 'r', encoding='utf-8') as f:
            session_data = json.load(f)

        client = PerplexityClient(api_key, session_name)
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


def display_welcome():
    """Display welcome message."""
    welcome_text = """
# Perplexity AI Text UI

Welcome to the Perplexity AI terminal interface!

Commands:
- Type your question or prompt to chat
- `/save [filename]` - Export conversation to markdown file
- `/sessions` - List all saved sessions
- `/load <session>` - Load a previous session
- `/usage` - Show current session usage statistics
- `/clear` - Clear conversation history
- `/model` - Change model
- `/help` - Show this help message
- `/quit` or `/exit` - Exit the application
"""
    console.print(Panel(Markdown(welcome_text), title="Welcome", border_style="cyan"))


def display_models():
    """Display available models in a table."""
    table = Table(title="Available Models", show_header=True, header_style="bold magenta")
    table.add_column("Choice", style="cyan", width=8)
    table.add_column("Name", style="green")
    table.add_column("Description", style="white")

    for choice, model in MODELS.items():
        table.add_row(choice, model["name"], model["description"])

    console.print(table)


def select_model() -> Optional[str]:
    """Prompt user to select a model."""
    display_models()

    choice = Prompt.ask(
        "\n[bold yellow]Select a model[/bold yellow]",
        choices=list(MODELS.keys()),
        default="2"
    )

    selected_model = MODELS[choice]
    console.print(f"\n[green]Selected:[/green] {selected_model['name']}")
    return selected_model["id"]


def display_sessions():
    """Display all saved sessions in a table."""
    sessions = PerplexityClient.list_sessions()

    if not sessions:
        console.print("\n[yellow]No saved sessions found.[/yellow]\n")
        return

    table = Table(title="Saved Sessions", show_header=True, header_style="bold magenta")
    table.add_column("Session Name", style="cyan")
    table.add_column("Created", style="green")
    table.add_column("Last Saved", style="green")
    table.add_column("Messages", style="yellow", justify="right")

    for session in sessions:
        created = session['created_at'][:19] if session['created_at'] != "Unknown" else "Unknown"
        saved = session['saved_at'][:19] if session['saved_at'] != "Unknown" else "Unknown"
        table.add_row(
            session['name'],
            created,
            saved,
            str(session['message_count'])
        )

    console.print(table)
    console.print()


def display_usage(client: PerplexityClient):
    """Display current session usage statistics."""
    usage = client.get_usage_summary()

    table = Table(title="Current Session Usage", show_header=True, header_style="bold magenta")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="green", justify="right")

    table.add_row("Total Tokens", f"{usage['total_tokens']:,}")
    table.add_row("Prompt Tokens", f"{usage['prompt_tokens']:,}")
    table.add_row("Completion Tokens", f"{usage['completion_tokens']:,}")
    table.add_row("Estimated Cost", f"${usage['estimated_cost']:.4f}")

    console.print()
    console.print(table)
    console.print()


def display_global_usage():
    """Display global usage statistics from all time."""
    if not USAGE_FILE.exists():
        console.print("\n[yellow]No usage data available yet.[/yellow]\n")
        return

    with open(USAGE_FILE, 'r') as f:
        usage_data = json.load(f)

    if not usage_data:
        console.print("\n[yellow]No usage data available yet.[/yellow]\n")
        return

    table = Table(title="Global Usage Statistics", show_header=True, header_style="bold magenta")
    table.add_column("Date", style="cyan")
    table.add_column("Model", style="green")
    table.add_column("Requests", style="yellow", justify="right")
    table.add_column("Total Tokens", style="yellow", justify="right")

    for date in sorted(usage_data.keys(), reverse=True)[:7]:  # Last 7 days
        for model, stats in usage_data[date].items():
            table.add_row(
                date,
                model,
                str(stats['requests']),
                f"{stats['total_tokens']:,}"
            )

    console.print()
    console.print(table)
    console.print("\n[dim]Showing last 7 days of usage[/dim]\n")


def main():
    """Main application loop."""
    # Check for API key
    api_key = os.getenv("PERPLEXITY_API_KEY")
    if not api_key:
        console.print("[red]Error: PERPLEXITY_API_KEY not found in environment variables.[/red]")
        console.print("[yellow]Please create a .env file with your API key (see .env.example)[/yellow]")
        sys.exit(1)

    # Initialize client
    client = PerplexityClient(api_key)

    # Display welcome
    display_welcome()

    # Select initial model
    current_model = select_model()
    client.session_metadata["model"] = current_model

    # Create prompt history
    history = InMemoryHistory()

    # Main loop
    console.print("\n[bold green]Ready to chat! Type your message or /help for commands.[/bold green]\n")
    console.print(f"[dim]Session: {client.session_name}[/dim]\n")

    while True:
        try:
            # Get user input with history support
            user_input = prompt(
                "You: ",
                history=history,
                multiline=False
            ).strip()

            if not user_input:
                continue

            # Handle commands
            if user_input.startswith("/"):
                command_parts = user_input.split(maxsplit=1)
                command = command_parts[0].lower()
                args = command_parts[1] if len(command_parts) > 1 else ""

                if command in ["/quit", "/exit"]:
                    # Auto-save session before exiting
                    if client.conversation_history:
                        try:
                            client.save_session()
                            console.print(f"[dim]Session saved: {client.session_name}[/dim]")
                        except Exception as e:
                            console.print(f"[yellow]Warning: Could not save session: {e}[/yellow]")
                    console.print("\n[yellow]Goodbye![/yellow]")
                    break

                elif command == "/save":
                    try:
                        filename = args.strip() if args else None
                        filepath = client.export_conversation(filename)
                        console.print(f"\n[green]Conversation exported to:[/green] {filepath}\n")
                    except Exception as e:
                        console.print(f"[red]Error exporting conversation: {e}[/red]\n")
                    continue

                elif command == "/sessions":
                    display_sessions()
                    continue

                elif command == "/load":
                    if not args:
                        console.print("[red]Please specify a session name: /load <session_name>[/red]\n")
                        display_sessions()
                        continue

                    try:
                        loaded_client = PerplexityClient.load_session(args.strip(), api_key)
                        if loaded_client:
                            client = loaded_client
                            current_model = client.session_metadata.get("model", current_model)
                            console.print(f"\n[green]Session loaded:[/green] {client.session_name}")
                            console.print(f"[dim]Messages: {len(client.conversation_history)}[/dim]\n")
                        else:
                            console.print(f"[red]Session not found: {args.strip()}[/red]\n")
                    except Exception as e:
                        console.print(f"[red]Error loading session: {e}[/red]\n")
                    continue

                elif command == "/usage":
                    display_usage(client)
                    display_global_usage()
                    continue

                elif command == "/clear":
                    client.clear_history()
                    console.print("\n[green]Conversation history cleared.[/green]\n")
                    continue

                elif command == "/model":
                    current_model = select_model()
                    client.session_metadata["model"] = current_model
                    console.print()
                    continue

                elif command == "/help":
                    display_welcome()
                    continue

                else:
                    console.print(f"[red]Unknown command: {user_input}[/red]")
                    console.print("[yellow]Type /help for available commands[/yellow]\n")
                    continue

            # Send message to API
            response = client.chat(user_input, current_model, stream=True)

            # Update session metadata
            if response:
                client.session_metadata["message_count"] = len(client.conversation_history)

                # Auto-save session after every 5 messages
                if len(client.conversation_history) % 10 == 0:
                    try:
                        client.save_session()
                    except Exception:
                        pass  # Silent fail on auto-save

        except KeyboardInterrupt:
            console.print("\n\n[yellow]Use /quit or /exit to exit the application[/yellow]\n")
            continue

        except EOFError:
            console.print("\n[yellow]Goodbye![/yellow]")
            break

        except Exception as e:
            console.print(f"\n[red]Unexpected error: {str(e)}[/red]\n")
            continue


if __name__ == "__main__":
    main()
