"""
FooterStatus widget - Shows streaming status and indicators at the bottom.
"""

import time
from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.reactive import reactive
from textual.widgets import Static


class FooterStatus(Static):
    """Footer status bar showing streaming indicators with elapsed time."""

    # CSS is in layout.tcss

    status_message = reactive("")
    elapsed_time = reactive(0.0)

    def __init__(self):
        super().__init__()
        self.status_message = "Ready"  # Show "Ready" when idle
        self.elapsed_time = 0.0
        self._start_time = None
        self._timer = None

    def compose(self) -> ComposeResult:
        """Compose the footer status with message and timer."""
        with Horizontal():
            yield Static("", id="footer-status-text")
            yield Static("", id="footer-status-timer")

    def watch_status_message(self, message: str) -> None:
        """Update status message when it changes."""
        try:
            status_text = self.query_one("#footer-status-text", Static)
            status_text.update(f"  {message}" if message else "  Ready")
        except:
            pass

    def watch_elapsed_time(self, elapsed: float) -> None:
        """Update elapsed time display."""
        try:
            timer_text = self.query_one("#footer-status-timer", Static)
            timer_text.update(f"{elapsed:.1f}s  " if elapsed > 0 else "")
        except:
            pass

    def _update_timer(self) -> None:
        """Update elapsed time (called by interval)."""
        if self._start_time is not None:
            self.elapsed_time = time.time() - self._start_time

    def set_thinking(self) -> None:
        """Show 'Thinking...' indicator and start timer."""
        # Stop existing timer if any (prevent multiple timers)
        if self._timer is not None:
            self._timer.stop()

        self.status_message = "⏳ Thinking..."
        self._start_time = time.time()
        self.elapsed_time = 0.0
        # Update timer every 100ms
        self._timer = self.set_interval(0.1, self._update_timer)

    def set_streaming(self) -> None:
        """Show 'Streaming...' indicator (keep timer running)."""
        self.status_message = "● Streaming response..."
        # Timer continues from thinking phase

    def clear(self) -> None:
        """Clear all status messages and stop timer."""
        self.status_message = "Ready"  # Return to idle state
        self.elapsed_time = 0.0
        self._start_time = None
        if self._timer is not None:
            self._timer.stop()
            self._timer = None
