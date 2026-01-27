"""
Adapter layer between TextualCompleter and textual-autocomplete library.

This module bridges our existing completion logic with the textual-autocomplete
dropdown system, converting our completion tuples to DropdownItem objects.

The adapter preserves all our existing completion logic (slash commands, @file,
@clipboard, @url, subcommands, etc.) while delegating UI rendering to the
battle-tested textual-autocomplete library.
"""

from typing import Callable, Iterable

from textual_autocomplete import DropdownItem

from .completer import TextualCompleter


class CompletionAdapter:
    """Adapter that converts TextualCompleter output to DropdownItem format."""

    def __init__(self, completer: TextualCompleter):
        """Initialize the adapter.

        Args:
            completer: TextualCompleter instance with our completion logic
        """
        self.completer = completer

    def get_dropdown_items(self, current_text: str) -> Iterable[DropdownItem]:
        """
        Get dropdown items for autocomplete.

        This is the callback function used by textual-autocomplete's AutoComplete.
        It converts our (completion, description) tuples to DropdownItem objects.

        Args:
            current_text: Current input text from the Input widget

        Returns:
            Iterable of DropdownItem objects for textual-autocomplete
        """
        # Get completions from our existing logic
        completions = self.completer.get_completions(current_text)

        # Convert to DropdownItem format
        for completion_text, description in completions:
            # Combine completion and description in main text
            # Use dim markup for description to make it less prominent
            if description:
                display_text = f"{completion_text} [dim]- {description}[/dim]"
            else:
                display_text = completion_text

            yield DropdownItem(
                main=display_text,         # The display text (with description)
                id=completion_text,        # Use completion_text as ID for insertion
            )


def create_completion_callback(completer: TextualCompleter) -> Callable[[str], Iterable[DropdownItem]]:
    """
    Create a completion callback function for textual-autocomplete.

    This is a convenience factory function that creates the adapter and returns
    its get_dropdown_items method as a callback.

    Args:
        completer: TextualCompleter instance

    Returns:
        Callback function suitable for AutoComplete(items=...)
    """
    adapter = CompletionAdapter(completer)
    return adapter.get_dropdown_items
