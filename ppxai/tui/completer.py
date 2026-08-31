"""
Autocomplete logic for Textual TUI.

Since v1.17.x, Textual delegates ALL autocomplete logic to
`engine.completion.complete()` — the same function used by Rich TUI
(in-process) and by Web + VSCode (via the `POST /complete` server
endpoint). This class is a thin adapter that:

1. Builds the completion context from the active EngineClient
   (working_dir, current_provider, live tool list), and
2. Translates the engine's stable dict schema into the
   `(replacement_text, description)` tuple shape that InputBox expects.

Subcommand tables (/tools, /usage, /checkpoint, /status, /theme),
`/model` + `/provider` name lookups, path-arg routing, @file refs,
and @git/@tree/@clipboard/@url context providers are all owned by the
engine. Do NOT re-introduce client-side tables here — every table here
used to drift against the Rich TUI copy. The whole point of the
v1.17.x autocomplete refactor was to kill this duplication.
"""

from pathlib import Path

from ..engine.completion import complete as engine_complete


class TextualCompleter:
    """Autocomplete handler for Textual TUI.

    `get_completions()` returns `(replacement_text, description)` tuples
    where `replacement_text` is the *full desired content* of the input
    box after applying the completion. InputBox sets
    `text_area.text = replacement_text` directly — no further
    transformation needed.
    """

    def __init__(self, working_dir: Path, engine_client=None):
        self.working_dir = working_dir
        self.engine_client = engine_client

    # ------------------------------------------------------------------
    # Context builders — pulled from the active EngineClient at request
    # time so /model, /provider, and /tools help <tool> complete against
    # live state rather than a stale snapshot.
    # ------------------------------------------------------------------

    def _get_current_provider(self) -> str | None:
        if self.engine_client is None:
            return None
        return getattr(self.engine_client, "provider_name", None) or None

    def _get_tool_names(self) -> list[tuple[str, str]]:
        if self.engine_client is None:
            return []
        tool_manager = getattr(self.engine_client, "tool_manager", None)
        if tool_manager is None:
            return []
        try:
            return [
                (t["name"], t.get("description", ""))
                for t in tool_manager.list_tools()
            ]
        except Exception:
            return []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_completions(self, text: str) -> list[tuple[str, str]]:
        """Return completion candidates for *text*.

        Each item is `(replacement_text, description)` where
        `replacement_text` is the full desired input-box content after
        applying the completion. The caller can set
        `text_area.text = replacement_text` directly.
        """
        cursor = len(text)
        items = engine_complete(
            text,
            cursor,
            working_dir=str(self.working_dir),
            current_provider=self._get_current_provider(),
            tool_names=self._get_tool_names(),
            client="textual",
        )

        completions: list[tuple[str, str]] = []
        for item in items:
            replace_start = item.get("replace_start", 0)
            # Cut off the chars the engine says to replace, then append
            # the completion text. For command-name completions we
            # additionally append a trailing space so the user can
            # immediately type arguments — matches the old behaviour.
            base = text[: cursor + replace_start]
            suffix = " " if item.get("kind") in ("command", "alias") else ""
            replacement = base + item["text"] + suffix
            completions.append((replacement, item.get("description", "")))

        return completions

    def update_working_dir(self, working_dir: Path) -> None:
        """Update the working directory for path completions."""
        self.working_dir = working_dir
