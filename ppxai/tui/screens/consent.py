"""Consent prompt for a parked agent run (T5 park, T8b Textual affordance).

A `/task` run that wants to spawn a sub-agent PARKS: the registry records
`waiting{kind: "consent"}` with a resume token and the run blocks until
answered, or until the consent TTL expires and resolves to a denial
(fail-closed).

VSCode raises a native QuickPick for this; this is Textual's equivalent. The
`/task respond <id> approve|deny` command remains the manual path and keeps
working — this screen only removes the need to notice `✋ waiting` in
`/task ls` first.

**Dismissal is not neutral.** Escape resolves to a denial rather than leaving
the dialog's outcome undefined, because a run left parked on a decision the
operator believes they declined is the worst of the three outcomes. The TTL
is still the backstop if the app never prompts at all.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.screen import Screen
from textual.widgets import Static

from ppxai.tui.keys import get_widget_bindings


class RunConsentScreen(Screen):
    """Ask the operator to approve or deny a parked run's spawn request.

    Dismisses with:
        True  — approve
        False — deny
        None  — deferred; the run stays parked and the TTL will deny it
    """

    BINDINGS = get_widget_bindings("RunConsentScreen")

    def __init__(self, run_id: str, prompt: str, ttl_s: float | None = None):
        super().__init__()
        self._run_id = run_id
        self._prompt = prompt
        self._ttl_s = ttl_s

    def compose(self) -> ComposeResult:
        ttl = (f"\n[dim]Unanswered, this denies automatically after "
               f"{int(self._ttl_s)}s.[/dim]" if self._ttl_s else "")
        yield Static(
            f"\n\n[bold yellow]✋ Agent run needs consent[/bold yellow]\n\n"
            f"[dim]run:[/dim] {self._run_id}\n\n"
            f"{self._prompt}\n"
            f"{ttl}\n\n"
            "[dim]Press:[/dim]\n"
            "  [cyan]A[/cyan] - Approve\n"
            "  [cyan]D[/cyan] - Deny\n"
            "  [cyan]Esc[/cyan] - Decide later (the TTL will deny)\n",
            id="consent-dialog",
        )

    def action_approve(self) -> None:
        self.dismiss(True)

    def action_deny(self) -> None:
        self.dismiss(False)

    def action_dismiss(self) -> None:
        """Defer. Deliberately distinct from deny.

        Answering `False` here would be a lie about what the operator did —
        they postponed, they did not refuse. The run stays parked and
        `/task respond` still works; the TTL remains the fail-closed backstop.
        """
        self.dismiss(None)
