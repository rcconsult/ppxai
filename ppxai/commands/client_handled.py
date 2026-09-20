"""
Client-handled commands — registered specs with no server handler.

ADR 0007 step 1b. `/token` and `/quit` used to live in
`engine/completion.py::_BUILTIN_SPECIAL_COMMANDS` as loose dicts, because
the registry had no way to express a command whose implementation is
bundled in the CLIENT rather than in a Python handler. `CommandSpec` grew
`client_action` / `client_action_clients` / `clients` in step 1a, so they
are ordinary registered specs now and the hand-written roster is gone.

What "client-handled" means here (ADR 0007 §Decision):

- **Dispatch happens in the client.** It is NOT "no server involvement" —
  `/token mint` calls `POST /v1/tokens` — and it is never "forward to the
  server and let it refuse": `/token set <value>` carries a secret, so a
  client that POSTed it to `/command/token` would already have leaked it
  into a request body and the server log before the refusal.
- **Python owns the declaration**, each client bundles the implementation
  of the named action. No executable code crosses the wire.

The server side of the contract lives here too (`client_handled_result`,
`client_handled_message`) so the three dispatch paths — Rich
(`commands/handler.py`), Textual (`tui/app.py`) and the HTTP route
(`server/routes/commands.py`) — say the same thing, and so none of them
echoes the arguments back.
"""

from .factory import CommandFactory, CommandSpec
from .results import ErrorResult, ResultStatus


def client_handled_message(spec: CommandSpec) -> str:
    """Human-readable refusal for a command this process cannot run.

    Deliberately argument-free: the caller's args may be a secret
    (`/token set <value>`), so nothing derived from them appears in the
    message, the result or any log line.
    """
    if spec.clients:
        where = ", ".join(sorted(spec.clients))
        return (
            f"/{spec.name} is handled by the client, not the server — "
            f"available in: {where}"
        )
    return f"/{spec.name} is handled by the client, not the server"


def client_handled_result(spec: CommandSpec) -> ErrorResult:
    """The envelope body for a client-handled command reaching dispatch.

    An `ErrorResult` (so `ok` is False and every existing client renders
    it) carrying a machine-readable marker in `metadata`: a client that
    reaches here has a routing bug, and `client_action` tells it which
    bundled action it should have run instead.
    """
    return ErrorResult(
        status=ResultStatus.ERROR,
        message=client_handled_message(spec),
        metadata={
            "client_handled": True,
            "command": spec.name,
            "client_action": spec.client_action,
            "clients": sorted(spec.clients) if spec.clients else None,
        },
        suggestions=[
            f"Run /{spec.name} in a client that implements "
            f"'{spec.client_action}'",
        ],
    )


# =============================================================================
# Command Registration
# =============================================================================

CommandFactory.register(CommandSpec(
    name="quit",
    description="Exit the application",
    category="system",
    # Owner decision (ADR 0007 plan, 2026-09-20): ONE spec — /exit is an
    # alias, not a second command. Rich (`commands/handler.py`) and
    # Textual (`tui/app.py`) intercept both names before the factory
    # lookup and end the process themselves; the spec exists so the
    # roster is complete, not to change that.
    #
    # Owner decision (2026-09-20, REVERSES the earlier "universal" call):
    # gated to the terminal clients only. In a GUI, ending the session is
    # a UI button workflow, not a command — the web app has a header
    # button for it (labelled "Leave"), and VSCode already has
    # Disconnect. Web and VSCode must never see /quit or /exit in
    # completion or /help. This also resolves a step 1b finding: /quit
    # was declared universal but no JS client implemented `app.quit`.
    clients=frozenset({"rich", "textual"}),
    aliases=["exit"],
    usage="/quit",
    client_action="app.quit",
))

CommandFactory.register(CommandSpec(
    name="token",
    description="Manage the /v1 API bearer token (status·set·mint·clear)",
    category="system",
    usage="/token [status|set|mint|clear]",
    # Genuinely client-side state: the credential store is the browser's
    # localStorage plus the in-memory ApiClient. The server can mint a
    # token but cannot attach it to the client's future requests.
    clients=frozenset({"web", "vscode"}),
    client_action="token.manage",
    subcommands=[
        ("status", "Show whether a /v1 bearer token is stored (masked)"),
        ("set",    "Store a token — prompts for the value; never type it inline"),
        ("mint",   "Mint + store a token via the loopback bootstrap (local server)"),
        ("clear",  "Remove the stored token"),
    ],
))
