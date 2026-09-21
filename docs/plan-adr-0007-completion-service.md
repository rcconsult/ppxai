# Plan — closing ADR 0007 (one command registry)

**Status: steps 1 (1a + 1b), 2, 2.5 and 3a (web) IMPLEMENTED; step 3b
(VSCode) and steps 4-5 PROPOSED, not started.**
Written 2026-09-20 on `bugfix/v1.19.3`; **rewritten the same day** after
the owner restated the goal. The first draft split the work (a) invert the
edge / (b) relocate / (c) roster, called (c) "a feature wearing the ADR's
clothes", and recommended carrying it under a separate record. **That was
backwards** — the roster is the goal and the edge inversion is its side
effect. This version is sequenced accordingly.

Every measured claim carries its verification command: the ADR's own 08-15
evidence decayed silently (it cited a module Item 65 had deleted), and this
file is written not to repeat that.

**Record:** [decisions/0007-completion-first-class-service.md](decisions/0007-completion-first-class-service.md)
· step 1 shipped v1.18.8 · steps 2 and 2.5 landed 2026-09-20 and step 3a
(web) on 2026-09-21, all on `bugfix/v1.19.3`, no target release.

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

> **Correction (2026-09-21): it was SIX.** `vscode-extension/src/shared/
> commands.ts` is a second, independent hand-written roster (31 entries),
> not a shared file — see step 3. **Three of the six are now gone:**
> `_BUILTIN_SPECIAL_COMMANDS` + `_CLIENT_GATES` (step 1b),
> `web/shared/commands.js` and the `app.js` fallback catalog (step 3a).
> Remaining: `CommandSpec` (the intended single source), the six
> `_*_SUBCOMMANDS` tables (step 4) and `commands.ts` (step 3b).

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

(The script above no longer runs: step 3a deleted `commands.js`. Point it
at `vscode-extension/src/shared/commands.ts` — regex
`r"^    '/([a-z-]+)':"` matches there too — to diff the one JS roster that
is left. Kept verbatim as the dated measurement it was.)

`CompletionCommandInfo` (the v1.18.8 seed) carries name / description /
hidden / alias data only — no `usage`, `category` or subcommands — so it
cannot replace `commands.js` as-is. The dispatch half of the server surface
exists (`POST /command/{name}`); the roster read endpoint landed with
step 2 in the SAME module
(`grep -n '@router' ppxai/server/routes/commands.py` now shows both).

## Steps — each ships alone

### 1. Enrich `CommandSpec` (server-only, no client change) — ✅ DONE (2026-09-20)

Add `subcommands`, `clients` gating, argument kinds and `client_action`.
Register client-handled specs for `token`, `quit`, `exit` — no server
handler, each naming a `client_action` from a fixed vocabulary (e.g.
`"token.manage"`, `"app.quit"`). Python declares the binding; each client
bundles the implementation. **No executable code crosses the wire** —
shipping JS from the server was considered and rejected (ADR 0007,
§Why this and not the alternatives). See §Migrating the client-handled
commands for the per-command contract. Widen (or replace)
`CompletionCommandInfo` to carry `usage`, `category`, subcommands.

**Decided 2026-09-20 (owner):**

- **`/exit` is an ALIAS of `/quit`** — one spec, `aliases=["exit"]`. Same
  behaviour, and aliases are the registry's native form
  (`CommandSpec.aliases`). NB: a colliding alias is only WARNED about in
  `CommandFactory.register` and then registered anyway — see the note under
  the convention below.
- **The canonical `client_action` vocabulary lives in PYTHON**, beside
  `CommandSpec`. The parity fence reads that one list and checks each JS
  client implements every name. A JS-side list would be a second source of
  truth — the thing this whole record exists to remove.

Initial vocabulary (step 1; widened to all 9 approved names by step 2.5 —
see that section for the seven hybrid rows):

| Command | `client_action` | `clients` |
|---|---|---|
| `/token` | `token.manage` | `{web, vscode}` |
| `/quit` (alias `/exit`) | `app.quit` | `{rich, textual}` (owner decision, 2026-09-20 — see below; was `universal` before that) |
| `/task` | `task.controller` | universal (`client_action_clients={web, vscode}`) |
| `/run` | `run.controller` | universal (`client_action_clients={web, vscode}`) |
| `/auto` | `auto.loop` | universal (`client_action_clients={web, vscode}`) |
| `/generate` `/explain` `/test` `/docs` `/debug` `/implement` | `coding.stream` | universal (`client_action_clients={vscode}`) |
| `/convert` | `coding.convert` | universal (`client_action_clients={vscode}`) |
| `/preview` | `preview.panel` | universal (`client_action_clients={vscode}`) |
| `/help` | `help.augment` | universal (`client_action_clients={vscode}`) |

**Decided 2026-09-20 (owner), REVERSES the initial vocabulary above:**
`/quit` (alias `/exit`) is gated to `clients={"rich", "textual"}`, not
universal. In a GUI, ending the session is a UI button workflow, not a
command — the web app has a header button for it (relabelled "Leave"),
and VSCode already has Disconnect. Web and VSCode must never see `/quit`
or `/exit` in completion or `/help`. This also resolves a step 1b
finding: `/quit` was declared universal but no JS client implemented the
`app.quit` action — the hybrid-commands table's "Pure client" row above
already needed the same fix.

**Resolved by measurement:** hybrid commands (`/task`, `/run`, `/auto`,
streaming, client-native UX) DO carry a `client_action`, scoped per client
— see §Hybrid commands. Legacy intercepts do not.

**Decided 2026-09-20 (owner): an action plus a client set**, not a
`{client: action}` mapping:

    client_action="task.controller",
    client_action_clients={"web", "vscode"},

It matches how `clients` gating already works in `completion.py`, and it is
the more compact form. What it commits to: every client that takes the
action takes the SAME named action — web's `RunController` and VSCode's
`getRunController()` are separate implementations of one name. If two
clients ever need different actions for one command, that is a schema
change, made deliberately.

Convention that makes the pair well-defined (proposed with the decision —
correct it if wrong):

- A client IN `client_action_clients` dispatches to the named action.
- A client NOT in it uses the server `handler` — so Rich/Textual need no
  entry and their behaviour is the default.
- `client_action_clients` ABSENT means "every client that can see the
  command" — the natural form for a spec with no handler at all
  (`/quit`: universal; `/token`: bounded by `clients={"web","vscode"}`).
- A spec with neither a `handler` nor a `client_action` is invalid and
  raises `ValueError` at registration (implemented in step 1a).

> **Correction (2026-09-20).** This plan said an invalid spec should fail
> "the way an alias collision does today". Alias collisions do NOT fail:
> `CommandFactory.register` logs a warning and then runs
> `cls._aliases[alias] = spec.name` unconditionally, so the newcomer takes
> the name. Because `get()` consults the alias map FIRST, an alias equal to
> an existing COMMAND name silently shadows that command. The hand-written
> note at `commands/coding.py:379` ("Removed \"t\" alias - conflicts with
> /tools") is someone working around this.
>
> **Decided 2026-09-20 (owner): alias collisions are a RELEASE GATE.**
> Aliases are code configuration, so a collision in the shipped roster must
> fail the suite, and the suite gates release —
> `tests/test_command_alias_collisions.py`. It reads the DECLARATIONS rather
> than `_aliases`, because registration overwrites and destroys the evidence.
> Runtime behaviour is deliberately unchanged: a user's
> `~/.ppxai/commands/*.py` still loads with warn-and-overwrite, so a
> collision there cannot stop the app from starting.

**Still open** (settle before coding): the shape of `clients` on a spec (a set of client ids, absent = universal — matching what
`completion.py:70-78` already does informally); how argument kinds are
expressed; whether subcommands are flat `(name, description)` pairs or
nested specs.

**Acceptance:** every entry in the six `_*_SUBCOMMANDS` tables and every
`commands.js` field has a home on a spec. Nothing consumes them yet.

**Step 1b findings (2026-09-20).** Registering `/token` and `/quit` as
real specs made `POST /command/{name}` reachable for them, and doing that
surfaced a pre-existing bug rather than introducing one:

- The route logged `args_preview` from the request BEFORE looking the
  command up, so `POST /command/token {"args":"set <bearer>"}` wrote the
  secret to the server debug log — and a typo'd `POST /command/tokn
  {"args":"set <secret>"}` leaked the same way via the 404 branch, since
  that branch logged the raw args too. Fixed in
  `ppxai/server/routes/commands.py::execute_command`: both the
  unknown-command and the client-handled branches now log only a fixed,
  args-free message, and `args_preview` is computed/logged only once the
  command is confirmed server-dispatched. Pinned by
  `tests/test_client_handled_dispatch.py::TestSecretNeverEchoed`.
- `CommandFactory.generate_help(client=...)` had accepted a `client`
  parameter it never used since v1.13.10 — dead plumbing from before the
  registry had per-client gating. Step 1b is the first thing that makes
  the parameter do something (it now filters by `spec.clients`).
- `commands/system.py::_help_client` originally returned `None` for
  `ServerCommandContext` — deliberately failing open — with a docstring
  claiming that was correct "while every gated command is gated to
  exactly {web, vscode}". Gating `/quit` to Rich/Textual only (owner
  decision, same date) broke that assumption: `ServerCommandContext`
  serves both web and VSCode over one HTTP surface with no per-request
  client id, so failing open made `/quit` leak into web/VSCode `/help`
  even though `generate_help(client="web")` correctly hid it. Fixed by
  widening `client_sees` to accept a CANDIDATE SET (`frozenset[str]`) in
  addition to a single client id or `None`: visible iff `clients`
  intersects the candidate set. `_help_client` now returns the named
  constant `SERVER_CLIENTS = frozenset({"web", "vscode"})`
  (`commands/factory.py`) for the server context instead of `None`.
  Fail-open for `client=None` is unchanged and still pinned by tests.
  The remaining, deliberate limitation stands: a command gated to only
  ONE of web/vscode is still over-listed for the other, until the
  roster endpoint (step 2) carries a real client id. Pinned by
  `tests/test_client_handled_dispatch.py::TestServerHelpUsesTheCandidateSet`
  (exercises the real `POST /command/help` route, unlike the
  direct-call `generate_help(client="web")` tests that stayed green
  through the whole regression) and `TestClientSeesCandidateSet`.

### 2. `GET /commands` — ✅ DONE (2026-09-20)

Serves the full snapshot. A few KB — no pagination, no lazy loading.
`/reload` (which re-imports `~/.ppxai/commands/` at runtime —
`commands/utility.py:187`) signals roster-changed through the envelope's
existing `events`, or `/state` carries an integer roster version; the
client refetches. **The payload stays on the endpoint; only the signal is
pushed.** Deliberately NOT AppState: that would cost the schema DTO, two
hand-written mirrors and the sentinel tests, for data that almost never
changes — the cost that stalled this record for three releases.

**Shipped shape.** `CommandFactory.roster(client=None) -> dict` in
`commands/factory.py` is THE serializer — `GET /commands`
(`server/routes/commands.py`, the same route module as
`POST /command/{name}`, so no new PyInstaller hiddenimport) returns it
verbatim, and Rich/Textual can call the same method in-process. Payload:
`{"version": int, "commands": [...]}`, one entry per CANONICAL command
sorted by name, aliases as a FIELD (`exit` appears only inside `/quit`'s
`aliases`), never anything callable. Per entry: `name`, `aliases`,
`description`, `usage`, `category`, `hidden`, `subcommands`
(`[{name, description}]`), `clients`, `client_action`,
`client_action_clients`, `client_handled`, `dispatch`. Fenced by
`tests/test_command_roster_endpoint.py` (53 tests).

**Decisions made while implementing (all four were coordinator calls;
none turned out wrong against the code):**

- **`dispatch` for a candidate SET is `"client"` only if EVERY candidate
  dispatches in the client** (`factory.dispatch_target`). The asymmetry
  is deliberate: over-reporting `"client"` breaks dispatch for a
  candidate that really does route server-side, while over-reporting
  `"server"` costs one round trip that the existing client-handled
  refusal envelope already answers cleanly. An empty candidate set names
  no client to dispatch in, so it is `"server"`. A single id and `None`
  defer to `CommandSpec.dispatches_in_client`, which already defines
  both.
- **ETag: YES**, weak, `W/"commands-<version>-<client|server>"`, with
  `If-None-Match` → 304 and `Cache-Control: no-cache`. The payload is a
  pure function of (registry version, audience), so the cache key needs
  nothing else, and FastAPI makes the 304 a three-line branch. Weak
  because the bytes are only promised semantically equal.
- **Auth posture: inherited, unchanged, and that is the correct
  answer.** Auth is GLOBAL middleware (`server/http.py::auth_middleware`
  → `server/auth.py::check_request`), not a per-route dependency, so
  `GET /commands` sits in exactly the same class as `POST /complete` and
  `POST /command/{name}` by virtue of its path: auth off when no
  provider enforces; when enforced, loopback UI exemption applies
  (`/commands` is under neither `/v1/agent` nor `/v1/tokens`, the two
  prefixes that stay protected even locally) and a remote caller needs a
  bearer. Nothing was opened or closed. Pinned by
  `TestAuthPostureMatchesComplete`, which runs the identical request
  against `/complete` under four auth conditions and compares status +
  `WWW-Authenticate`.
- **The step-1b over-listing limitation is CLOSED, additively.**
  `CommandRequest` grew an optional `client` field (same shape
  `POST /complete` already had), validated against `KNOWN_CLIENTS` by
  the route (400 if unknown, and the rejection quotes only the id, never
  `args`), threaded into `ServerCommandContext(engine, client=...)` —
  Pattern B only, per ADR 0002 — and preferred by
  `commands/system.py::_help_client`, which falls back to
  `SERVER_CLIENTS` when absent. Every shipped client sends no `client`
  field, so their behaviour is byte-identical; pinned both ways by
  `TestExplicitClientClosesTheOverListing`
  (tests/test_client_handled_dispatch.py) and
  `TestCommandRequestClientField`.

**The change signal.** `SideEffectKind.REFRESH_COMMAND_ROSTER`
(`"refresh_command_roster"`, payload `{version}`), emitted by `/reload`
on BOTH branches — a reload that finds no user directory still
unregistered whatever custom commands were loaded before. Kinds are an
open enum ("clients ignore unknown kinds"), so no JS/TS change is needed
until step 3. **No cross-language sentinel forced a mirror edit**: the
only sentinel deriving from `SideEffectKind.all_kinds()` is
`tests/test_command_envelope.py::TestSideEffectKindTaxonomy` (Python,
updated) plus the `SideEffect` docstring; the web/VSCode drift fences
(`test_web_shared_modules.py`, `test_vscode_step5a_helpers.py`) hardcode
their OWN expected sets and are not derived from Python, so
`web/shared/side-effects.js` and
`vscode-extension/src/sideEffectsHandler.ts` were left untouched.

**Roster version.** `CommandFactory._roster_version`, bumped in the
three places the registry actually changes — `register`, `unregister`,
`clear`. `reload_user_commands` needs no bump of its own: it goes
through both. Read via `CommandFactory.roster_version()`.

**Finding.** The hybrid family (`/task`, `/run`, `/auto`) reports
`dispatch == "server"` today, because step 1 defined `CLIENT_ACTIONS` as
`{"token.manage", "app.quit"}` only — no hybrid command carries a
`client_action` yet. That is correct-by-construction (the roster must
not guess), but it means step 3's JS clients cannot yet use `dispatch`
to replace their hardcoded intercept `if`-chains for those three; the
chains stay until the hybrid actions are declared. Pinned by
`TestClientGating::test_hybrid_family_still_dispatches_server_side` so
the day they are declared, the test says so.

### 2.5 Declare the hybrid client actions — ✅ DONE (2026-09-20)

Step 2's own finding: `GET /commands` reported `dispatch == "server"` for
`/task`, `/run`, `/auto` because no hybrid command carried a
`client_action` — false for web/VSCode, whose JS controllers actually run
them. Left alone, step 3's JS clients could not use the roster's
`dispatch` field to retire their hardcoded intercept `if`-chains for
those commands, so this had to land BEFORE step 3. **Server-only**: no
JS/TS changed, since the client implementations already exist (this step
only declares what already runs).

Owner-approved vocabulary (2026-09-20), added to `CLIENT_ACTIONS`
alongside the existing `token.manage` and `app.quit`:

| Command(s) | `client_action` | `client_action_clients` |
|---|---|---|
| `/task` | `task.controller` | `{"web", "vscode"}` |
| `/run` | `run.controller` | `{"web", "vscode"}` |
| `/auto` | `auto.loop` | `{"web", "vscode"}` |
| `/generate` `/explain` `/test` `/docs` `/debug` `/implement` | `coding.stream` | `{"vscode"}` |
| `/convert` | `coding.convert` | `{"vscode"}` |
| `/preview` | `preview.panel` | `{"vscode"}` |
| `/help` | `help.augment` | `{"vscode"}` |

Each spec KEEPS its `handler` — these are hybrids, not client-handled:
the Python handler still serves Rich/Textual in-process
(`spec.handler is None` stays False, so `POST /command/<name>` still
executes it, and `is_client_handled` stays False), while `client_action`
serves the listed clients. The six coding commands deliberately share
ONE action, `coding.stream`: the client implementation receives the
command name as a parameter, mirroring VSCode's `CHAT_SHAPED_TASKS` map
(`chatPanel.ts`), which already dispatches all six through one function.
`/convert` is chat-shaped too but has distinct arg parsing
(`handleConvertCommand`), so it keeps its own action name rather than
folding into `coding.stream`. Web does not intercept the coding
commands, `/convert` or `/preview` — their `client_action_clients` is
`{"vscode"}` only, and web falls through to the server handler for all
of them. Web's `/help` intercept exists only for a shim step 3 deletes
(`_appendExperimentalHelp`), so `/help` is `{"vscode"}` only too, for
VSCode's real keyboard-shortcut augmentation.

Verified against the real client code before declaring, per
`docs/plan-adr-0007-completion-service.md` §Hybrid commands:
`command-dispatcher.js`'s five intercepts (`/auto`, `/run`, `/task`,
`/token`, `/help`) and `chatPanel.ts`'s twelve (`CHAT_SHAPED_TASKS` six +
`convert`, `auto`, `preview`, `task`, `run`, `token`, `help`) — the
acknowledged-legacy five (`/tools`, `/checkpoint`, `/context`, `/ls`,
`/tree`) were deliberately left undeclared, per the owner's "do not bless
debt" instruction; they stay in step 5's shrinking baseline.

Dispatch/`client_handled` decision points were checked for a
`client_action`-keyed bug (the risk step 1's `is_client_handled` docstring
calls out): `server/routes/commands.py::execute_command` keys on
`spec.handler is None`; `ppxai/tui/app.py::_handle_command` and
`ppxai/commands/handler.py` (Rich's dispatch path) both key on the same
condition. None keyed on `client_action` presence — no bug found, no fix
needed.

`tests/test_command_roster_endpoint.py::TestClientGating::
test_hybrid_family_still_dispatches_server_side` (written in step 2 to
fail the day this landed) was replaced with tests for the table above.

### 3. JS clients fetch at startup — split into 3a (web) and 3b (VSCode)

**Finding that forced the split (2026-09-21).** The two JS clients do NOT
share one roster file. `ppxai/web/shared/commands.js` and
`vscode-extension/src/shared/commands.ts` are **two independent
hand-written copies** — the TS one has 31 entries and its own drift (it
lists neither `/run`, `/task` nor `/token`, all three of which
`chatPanel.ts` intercepts at runtime, so VSCode's autocomplete and help
never offered them). `commands.js`'s header claims it is "the single
source of truth across the Desktop Web App and the VSCode Extension",
which was already false. Counting the TS copy, the ADR's "five places"
is really **six**. Deleting the web copy therefore touches nothing under
`vscode-extension/`, and the two halves ship separately.

#### 3a. Web — ✅ DONE (2026-09-21)

`ppxai/web/shared/command-roster.js` (`CommandRoster`) fetches
`GET /commands?client=web` once from `app.init()` through the existing
`ApiClient` (new `getCommandRoster(client)`), caches it, resolves
canonical names AND aliases, and refetches on the
`refresh_command_roster` side effect (handler added to
`web/shared/side-effects.js`, which stays — it is a BEHAVIOUR mirror).
`POST /command/{name}` bodies now carry `client: "web"`, which closes the
`/help` over-listing for web.

`CommandDispatcher.dispatch()` became data-driven: resolve the typed
name through the roster, and if the entry's `dispatch === "client"` call
the bundled implementation registered for its `client_action` —

    CommandDispatcher.CLIENT_ACTIONS = {
        'token.manage'   -> _handleTokenCommand
        'task.controller'-> this.tasks.handle   (via _viaController)
        'run.controller' -> this.runs.handle    (via _viaController)
        'auto.loop'      -> _dispatchAgent
    }

— else POST to the factory. An action the roster names that web does not
implement produces a clear error and is **never** forwarded. The
VSCode-only actions (`coding.stream`, `coding.convert`, `preview.panel`,
`help.augment`) never reach the table: the server reports
`dispatch == "server"` for them when asked `?client=web`.

**Decision (owner requirement): FAIL CLOSED.** The `/token set <value>`
guarantee used to be structural — the hardcoded branch ran before the
`_dispatchToFactory` fallthrough. With routing in data, an unavailable
roster would otherwise mean "forward everything", i.e. exactly the leak
step 1b fixed server-side. So the roster gate is the FIRST thing
`dispatch()` can leave on: no roster → retry the fetch once inline
(self-heal), and if that fails, refuse, explain, and return. The
explanation names **version skew** explicitly, because the web assets are
served from `~/.ppxai/web` and can be newer than the running server,
which then 404s `/commands`
(`docs/lessons/web-assets-served-from-ppxai-home.md`). Streaming
(chat-shaped) commands are inside the gate too — fail closed means
closed. Plain chat messages never touch `dispatch()` and are unaffected.
**No hardcoded `/token` escape hatch**: a per-name special case would be
a second roster again.

**Deletions.** `web/shared/commands.js` (376 lines) and its `<script>`
tag; the inline fallback catalog in `app.js` (`this.slashCommands`, ~30
commands); `_appendExperimentalHelp()` and the `/help` intercept that
existed only to call it. `web/shared/index.js` (an unimported ES-module
barrel) re-exported `commands.js` and now re-exports `CommandRoster`.

**Consumers found, and what replaced them.** Exactly two:
`app.js:196` assigned `this.slashCommands`, and
`command-dispatcher.js::_appendExperimentalHelp` read it. Nothing else.
Autocomplete was already server-side (`POST /complete`), so
`commands.js`'s `isSlashCommand` / `parseCommand` / `generateHelpText` /
`getCommandsByCategory` / `AI_FORWARDED_COMMANDS` helpers had **no web
consumer at all** — `generateHelpText` had been dead since v1.18.1
(`test_help_command_reconciliation.py` retired it) and
`AI_FORWARDED_COMMANDS` was superseded by the dispatcher's own
`STREAMING_COMMANDS`. They needed no roster-backed replacement; they were
deleted with the file.

**Bug fixed in passing.** `_dispatchAgent` sent a bare `/auto` to
`POST /command/agent`, but ADR 0011 renamed the command to `auto` with NO
alias, so it had been 404-ing ("Unknown command: /agent"). Now posts
`auto`.

**Confirmed by running the real UI** (`PPXAI_WEB_DIR=$PWD/ppxai/web`,
`ppxai-server` on a spare port, Playwright `live` project): web `/help`
lists `/token`, `/run` and `/task` **once each** — the double-listing the
plan flagged as "confirmed by source reading" is gone.

**Tests.**

| File | Disposition |
|---|---|
| `tests/test_client_handled_commands_contract.py` | Part B's WEB half rewritten (VSCode half untouched). The old invariant — `cmd === '/token'` precedes `_dispatchToFactory(` — deliberately no longer exists. New source-text helpers, each mutation-verified in the same file: the fail-closed gate precedes every dispatch path; the client-dispatch branch precedes (and returns before) the factory fallthrough; NO per-name escape hatch survives; the action registry implements every action Python declares for web (read off `iter_completion_specs()`, not a hand-copied list) |
| `tests/test_web_command_roster_dispatch_behavior.py` | **New.** Drives the REAL dispatcher + roster under Node against a call-logging fake `ApiClient` (the `test_agent_run_controller_behavior.py` idiom): all four client actions; routing flips when the ROSTER flips; alias `/cat` → canonical `show`; server dispatch carries `client:"web"`; unknown action → error + no POST; **no roster → `/token set <secret>` issues nothing but the roster retry and the secret appears in no payload**; refetch on the side effect (and a same-version signal is a no-op); a failed refetch keeps the working roster. The two security scenarios are mutation-verified: a scratch copy of the dispatcher with the gate removed, and one with the client branch bypassed, must both FAIL the harness |
| `tests/test_shared_commands.py` | Retargeted, not deleted. Its web half is inverted into deletion fences (`commands.js` stays gone; `index.html` stops loading it; `app.js` has no catalog) plus fences on the replacement module. Its VSCode **parity** half now compares `commands.ts` against the **Python registry** instead of against `commands.js` — the old comparison stayed green while both JS copies drifted from Python. The `/run`·`/task`·`/token` gap is pinned as an explicit known-gap test that fails the day step 3b (or a hand patch) closes it |
| `tests/test_vscode_task_controller.py` | `WEB_COMMANDS` (deleted file) → `TS_COMMANDS` + direct `CommandFactory` checks, since web's catalog IS the registry now |
| `tests/test_web_command_dispatcher_v18_1.py` | Size fence 340 → 480 lines with the reason recorded in its threshold history (net code is flat; the growth is the fail-closed rationale + the registry's comments). `this.runs?.handle(` assertion → the registry binding `'run.controller' … _viaController(this.runs` (plus the same for `/task`) |
| `tests/test_web_shared_modules.py` | Added script-order fence (`api-client.js` < `command-roster.js` < `command-dispatcher.js`) and `refresh_command_roster` to the web side-effect kind set |
| `tests/test_help_command_reconciliation.py`, `tests/test_preview.py` | Prose only — both merely NAMED `commands.js`. The former's "the JS-side table can stay for client-side autocomplete" caveat has expired and says so |
| `tests/e2e/live-app.spec.ts` | New `command roster (ADR 0007 step 3a)` describe block against the real UI: roster fetched at boot with exactly the four client-dispatch entries, `/quit` invisible to web, `/cat` resolving to `show`; `/help` listing each of `/token`·`/run`·`/task` once and POSTing `client:"web"`; `/token status` with no `POST /command/token`; and the fail-closed path with the roster knocked out |

`tests/e2e/*-harness.html` carried no `commands.js` script tag — checked,
nothing to change.

**Finding, recorded not fixed.** In a real browser the typed line leaves
the client on two PRE-EXISTING paths before routing is even consulted:
`showSystemMessage`'s `> <input>` chat echo is mirrored to
`POST /client-log`, and the composer sends its buffer to `POST /complete`
for autocomplete. So `/token set <secret>` **inline** still reaches the
server debug log — which is precisely why bare `/token set` uses
`window.prompt` and why the inline form answers with a "consider rotating
this token" warning. Unchanged by this step and out of its contract
(§correctness contract item 4 is about the command-dispatch path), but
the live e2e test now pins the exact set of paths so it cannot grow
silently.

#### 3b. VSCode — not started

`vscode-extension/src/shared/commands.ts` (31 entries) and
`chatPanel.ts`'s twelve hardcoded intercepts. Independent of 3a per the
finding above. Note VSCode needs the same fail-closed decision, and the
extension host's stakes are higher (it runs with the user's full
privileges — see ADR 0007 §Why this and not the alternatives).

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
| `/quit`, `/exit` | `_BUILTIN_SPECIAL_COMMANDS`, universal | ends the client process | ONE spec: `/quit` with `aliases=["exit"]` (decided 2026-09-20), `client_action="app.quit"`, `clients={"rich","textual"}` (owner decision, 2026-09-20, reverses "universal" — ending a session is a GUI button workflow, not a command) |
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

   **RESOLVED in step 3a (2026-09-21)** — `_appendExperimentalHelp` is
   deleted and web `/help` comes from the registry alone, filtered by
   the `client:"web"` the client now sends. Verified against a running
   UI (Playwright `live` project): `/token`, `/run` and `/task` each
   appear exactly once. The finding as it stood:

   **Known-until-step-3 (confirmed by source reading, 2026-09-20, once
   step 1b made `/token` a registered spec):** web `/help` now lists
   `/token` **twice** — once from the server catalog (`_dispatchToFactory
   ('help', '')`, which includes it since `clients={"web","vscode"}`) and
   once from `_appendExperimentalHelp()` (`command-dispatcher.js`), which
   still reads it from the JS-side `commands.js` catalog unconditionally.
   And `commands.js`'s `/token` description ("Manage the bearer token
   attached to /v1 API calls (status|set|mint|clear)") reads differently
   from the Python spec's ("Manage the /v1 API bearer token
   (status·set·mint·clear)", `ppxai/commands/client_handled.py`) — same
   meaning, different wording, another second source of truth step 3
   collapses.

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
   resolution in `CommandFactory.get()` and publication via `iter_completion_specs()`
   (`is_alias` / `canonical`). `/exit` as an alias of `/quit` is native.

**Deletions that prove the migration is complete** — if any survives, a
second roster still exists:

| Deletion | Status |
|---|---|
| `_BUILTIN_SPECIAL_COMMANDS` + `_CLIENT_GATES` (`engine/completion.py`), and `_TOKEN_SUBCOMMANDS` with them | ✅ DONE — step 1b, 2026-09-20 |
| `_appendExperimentalHelp()` (`command-dispatcher.js`) and the `/help` intercept that existed only to call it | ✅ DONE — step 3a, 2026-09-21 |
| the inline fallback catalog (`app.js:199`, `this.slashCommands`) | ✅ DONE — step 3a |
| `web/shared/commands.js` in full — including the alias entries restated as standalone commands (`/cat`, `/sh`, `/term`) | ✅ DONE — step 3a; `CommandRoster.resolve()` reads the `aliases` FIELD |
| the five hardcoded `if (cmd === '/…')` intercepts in `command-dispatcher.js` | ✅ DONE — step 3a; routing is the roster's `dispatch` field. Fenced by `assert_web_has_no_per_name_escape_hatch` |
| `vscode-extension/src/shared/commands.ts` and `chatPanel.ts`'s twelve intercepts | ⬜ step 3b |
| the six `_*_SUBCOMMANDS` tables (`engine/completion.py`) | ⬜ step 4 |

Not a deletion and deliberately so: `web/shared/side-effects.js` stays —
it is a BEHAVIOUR mirror (ADR 0007 §Which mirrors can go), and step 3a
ADDED a handler to it (`refresh_command_roster`).

## Hybrid commands — dispatch routing becomes data

Measured 2026-09-20. "Do I POST this to `/command/<name>` or handle it
here?" is a hardcoded `if`-chain in each JS client, and the chains differ:
**web intercepts 5 commands** (`command-dispatcher.js`), **VSCode 12**
(`chatPanel.ts:1140-1220`). Nothing records which client handles what.

> **Update (2026-09-21).** Web's five are gone — step 3a replaced the
> chain with the roster's `dispatch` field plus a `client_action` →
> implementation registry. VSCode's twelve remain until step 3b, so the
> counts to re-measure are now `0` and `12`.

    grep -nE "if \(cmd === '/[a-z-]+'" ppxai/web/shared/command-dispatcher.js
    grep -nE "(^|[^a-zA-Z])command === '[a-z-]+'" vscode-extension/src/chatPanel.ts | grep -v subcommand

(The `grep -v subcommand` matters: without it `subcommand === 'clear'`
inflates VSCode's count to 16 — a mistake made and caught while writing this.)

The VSCode block documents its own intercepts, and they are five kinds:

| Kind | Commands | Gets a `client_action`? |
|---|---|---|
| Pure client | `/token` (`token.manage`), `/quit` (`app.quit`) | **Yes**, and NO server handler |
| Client-driven family | `/task` (`task.controller`), `/run` (`run.controller`), `/auto` (`auto.loop`) — JS controllers drive `/v1/agent/*`; JS never calls `POST /command/task` | **Yes, per client** — `handler=` serves Rich/Textual in-process, `client_action` serves web/VSCode. Declared step 2.5 |
| Streaming | `/convert` (`coding.convert`), coding tasks — `/generate` `/explain` `/test` `/docs` `/debug` `/implement` (`coding.stream`, one action shared by all six, VSCode-only) — the factory handler blocks on the LLM, so the client streams instead | **Yes, per client** — VSCode only. Declared step 2.5 |
| Client-native UX | `/preview` (`preview.panel`, own WebviewPanel), `/help` (`help.augment`, factory output + VSCode shortcuts) — both VSCode-only | **Yes** — `/help` wraps the factory rather than replacing it. Declared step 2.5 |
| **Acknowledged legacy** | `/tools`, `/checkpoint`, `/context`, `/ls`, `/tree` — the code says *"These hit bespoke REST today; full factory routing is a later phase"* | **NO.** Do not bless debt. These migrate to factory routing; the fence carries them as a shrinking baseline |

So `client_action` is **scoped by client** (via `client_action_clients`), not a boolean on the spec: a
command may have a Python handler AND a client action, and which one runs
depends on who is asking. `/token` is the degenerate case with no handler.

**Consequence for the parity fence (step 5):** every command a client
intercepts must be declared with a `client_action` for that client, or sit in
an explicit legacy baseline. On day one that baseline is exactly the five
legacy VSCode intercepts, and it may only shrink — the same discipline as
`BASELINE` in `tests/test_no_new_lazy_imports.py`.

## Note for step 2+ — PyInstaller hiddenimports

A new command module (like `ppxai/commands/client_handled.py` in step 1b)
must also be added as a hiddenimport in **all three** of `ppxai.spec`,
`ppxaide.spec` and `ppxai-server.spec`, or
`tests/test_pyinstaller_spec_completeness.py` fails. Easy to miss because
the module works fine in `uv run` (regular import machinery) and only
breaks in a PyInstaller-built binary where nothing imports it directly —
side-effect-only registration modules are exactly the shape PyInstaller's
static analysis misses.

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
