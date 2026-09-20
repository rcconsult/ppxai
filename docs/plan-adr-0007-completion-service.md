# Plan — closing ADR 0007 (one command registry)

**Status: PROPOSED, nothing started.** Written 2026-09-20 on
`bugfix/v1.19.3`; **rewritten the same day** after the owner restated the
goal. The first draft split the work (a) invert the edge / (b) relocate /
(c) roster, called (c) "a feature wearing the ADR's clothes", and
recommended carrying it under a separate record. **That was backwards** —
the roster is the goal and the edge inversion is its side effect. This
version is sequenced accordingly.

Every measured claim carries its verification command: the ADR's own 08-15
evidence decayed silently (it cited a module Item 65 had deleted), and this
file is written not to repeat that.

**Record:** [decisions/0007-completion-first-class-service.md](decisions/0007-completion-first-class-service.md)
· step 1 shipped v1.18.8 · step 2 open, no target release.

## The goal

**A command is defined once; everything else is derived.** One declaration
in the Python registry propagates to completion, `/help`, palettes and
menus in every client. In-process clients read the registry directly;
server-mediated clients fetch it from an endpoint at startup.

## Measured distance from the goal (2026-09-20)

Command metadata lives in **five places**: `CommandSpec`;
`web/shared/commands.js` (376 hand-written lines); an inline fallback
catalog at `web/app.js:199`; six `_*_SUBCOMMANDS` tables in
`engine/completion.py`; and `_BUILTIN_SPECIAL_COMMANDS` in the same file.

**Diff the rosters against canonical names AND aliases** — comparing
canonical-only produces false "JS-only" hits (the first draft of this plan
made exactly that mistake and reported `cat`, `sh`, `term` as JS-only; they
are registered aliases):

    uv run python - <<'PY'
    import re
    from ppxai.commands.factory import CommandFactory
    infos = list(CommandFactory.iter_completion_specs())
    names = {i.name for i in infos}                      # canonical + aliases
    js = set(re.findall(r"^    '/([a-z-]+)':", open("ppxai/web/shared/commands.js").read(), re.M))
    print("JS-only:", sorted(js - names))
    print("Python-only:", sorted({i.canonical for i in infos if not i.hidden} - js))
    PY

- JS-only: **`token`** (one command).
- Python-only: `attach autoroute copy debug-log doctor keys preview-log reload undo`

`CompletionCommandInfo` (the v1.18.8 seed) carries name / description /
hidden / alias data only — no `usage`, `category` or subcommands — so it
cannot replace `commands.js` as-is. The dispatch half of the server surface
exists (`POST /command/{name}`); a roster read endpoint does not
(`grep -n '@router' ppxai/server/routes/commands.py`).

## Steps — each ships alone

### 1. Enrich `CommandSpec` (server-only, no client change)

Add `subcommands`, `clients` gating, argument kinds and `client_action`.
Register client-handled specs for `token`, `quit`, `exit` — no server
handler, each naming a `client_action` from a fixed vocabulary (e.g.
`"token.manage"`, `"app.quit"`). Python declares the binding; each client
bundles the implementation. **No executable code crosses the wire** —
shipping JS from the server was considered and rejected (ADR 0007,
§Why this and not the alternatives). See §Migrating the client-handled
commands for the per-command contract. Widen (or replace)
`CompletionCommandInfo` to carry `usage`, `category`, subcommands.

**Open design questions** (settle before coding): the `client_action`
vocabulary — its initial names and where the canonical list lives so both
JS clients and the parity fence read the same one; the shape of `clients`
on a spec (a set of client ids, absent = universal — matching what
`completion.py:70-78` already does informally); how argument kinds are
expressed; whether subcommands are flat `(name, description)` pairs or
nested specs.

**Acceptance:** every entry in the six `_*_SUBCOMMANDS` tables and every
`commands.js` field has a home on a spec. Nothing consumes them yet.

### 2. `GET /commands`

Serves the full snapshot. A few KB — no pagination, no lazy loading.
`/reload` (which re-imports `~/.ppxai/commands/` at runtime —
`commands/utility.py:187`) signals roster-changed through the envelope's
existing `events`, or `/state` carries an integer roster version; the
client refetches. **The payload stays on the endpoint; only the signal is
pushed.** Deliberately NOT AppState: that would cost the schema DTO, two
hand-written mirrors and the sentinel tests, for data that almost never
changes — the cost that stalled this record for three releases.

### 3. JS clients fetch at startup

Web and VSCode load the roster from `GET /commands`. `commands.js` becomes
a loader, then is deleted. `app.js:196` (`this.slashCommands`) is the
current consumer.

### 4. Derive, don't restate

Completion's subcommand tables and `/help` read the spec. **At this point
`engine/completion.py` stops importing `CommandFactory`** — the layer
inversion and the `engine → commands → engine` package cycle close as a
side effect. Delete `TestEngineCompletionStaysALeaf` (its own failure
message says when).

Acceptance: `grep -rn 'from \.\.commands' ppxai/engine/` returns nothing.

### 5. Parity fence

A test that fails when any client renders a command the registry does not
declare, when the registry declares one a client does not render, or when a
`client_action` named in Python has no implementation in a client listed in
that spec's `clients`. The
rosters drifted silently; this is what stops a repeat.

## Migrating the client-handled commands — the correctness contract

Owner requirement (2026-09-20): the JS-side commands must land in the
Python command infrastructure **correctly**, not just be listed there.
"Correctly" means each row below stays true after the move.

| Command | Today | Why it is client-handled | Must hold after migration |
|---|---|---|---|
| `/token` | JS dispatcher branch (`command-dispatcher.js:111`), VSCode branch (`chatPanel.ts:1185`); declared in `_BUILTIN_SPECIAL_COMMANDS` with `clients={web,vscode}` | its **state** is client-side: the credential store is the browser's `localStorage` + the in-memory `ApiClient`. NOT Python-free — `mint` calls `POST /v1/tokens` (`server/routes/tokens_v1.py`); `status`/`set`/`clear` are pure client. The server can mint a token but cannot attach it to the client's future requests, so the client must orchestrate | spec is `client_handled`; `clients={web,vscode}`; subcommands `status·set·mint·clear` on the spec; **Rich/Textual never see it** in completion or `/help`; `POST /command/token` refuses cleanly rather than 404-ing |
| `/quit`, `/exit` | `_BUILTIN_SPECIAL_COMMANDS`, universal | ends the client process | spec is `client_handled`, no `clients` restriction; decide whether `/exit` is an ALIAS of `/quit` (one spec) or a second spec — aliases are the registry's native form |
| `/cat` | JS standalone entry "Alias for /show" | — it is NOT client-handled | **nothing to migrate**: already a registered alias. JS stops restating it; the endpoint serves aliases |
| `/sh`, `/term` | JS standalone entries "Alias for /terminal" | — not client-handled | same: already registered aliases |

**Four behaviours that must not regress**, each needing a test BEFORE the
move so the migration is verified rather than assumed:

1. **Client gating.** `_client_allows()` today fails OPEN for `client=None`
   (legacy callers see everything). That semantics moves onto the spec
   unchanged, or it is changed deliberately — not by accident.
2. **Dispatch of a client-handled command.** Today `/token` never reaches
   the server. Once it is a registered spec, `POST /command/token` becomes
   reachable: it must answer with a clear "handled by the client" envelope,
   not run anything and not look like an unknown command.
3. **`/help` is single-sourced.** Web `/help` is currently stitched:
   server catalog + `_appendExperimentalHelp()` appending `/run`, `/task`,
   `/token` as "Experimental (web-only)". The comment there says the
   CommandFactory "doesn't know about these", which has been **false for
   `/run` and `/task` since T8b** — so web `/help` plausibly lists them
   twice and mislabels them web-only (not confirmed against a running UI).
   After migration `_appendExperimentalHelp` is deleted and `/help` comes
   from the registry alone, filtered by `clients`.

4. **`/token set` never transits the command-dispatch path.** The handler
   already treats the value as a secret: bare `/token set` uses
   `window.prompt` so the token is not echoed, and the inline form warns it
   "was echoed into the chat + debug log… consider rotating". If a
   registered spec caused `/token set <value>` to be POSTed to
   `/command/token`, the secret would land in a command body and server
   logs. The published snapshot must carry the flag so the client knows
   BEFORE dispatching. `client_handled` must therefore mean **dispatch happens in the
   client** — not "no server involvement" (`mint` is server-backed) and
   never "forward to the server and let it refuse".

   Aliases need no schema work: `CommandSpec.aliases` exists, with
   collision checks at registration (`factory.py:149`), resolution in
   `get()` (`:186`) and publication via `iter_completion_specs()`
   (`is_alias` / `canonical`). `/exit` as an alias of `/quit` is native.

**Deletions that prove the migration is complete** — if any survives, a
second roster still exists: `_BUILTIN_SPECIAL_COMMANDS` and `_CLIENT_GATES`
(`engine/completion.py`), `_appendExperimentalHelp`
(`command-dispatcher.js`), the inline fallback catalog (`app.js:199`), and
the alias entries in `commands.js`.

## Explicitly not in the path

- **A `CompletionService` DI class.** A service holding a context
  collaborator while its callers still scrape context and pass it in is
  worse than either endpoint. Build it only if step 4 leaves a real need.
- **Relocating to `ppxai/completion/`.** Once step 4 removes the upward
  import, where the module sits is cosmetic. Optional.
- **Collapsing the three context scrapers** (`rich/main.py:217`,
  `tui/completer.py:79`, `routes/completion.py:89`). Real duplication,
  small, independent — do it opportunistically, not as a gate.

## Guard in place meanwhile

`tests/test_no_new_lazy_imports.py::TestEngineCompletionStaysALeaf`
(2026-09-20). The package cycle is proven, not inferred: a module-scope
import of `engine.completion` from `engine/client.py` kills the pytest run
at collection with a partially-initialized-module `ImportError`.
