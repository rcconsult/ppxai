# Plan — closing ADR 0007 (one command registry)

**Status: ALL FIVE STEPS IMPLEMENTED** — 1 (1a + 1b), 2, 2.5, 3a (web),
3a-sec (sensitive subcommands), 3b (VSCode), 4 (derive, don't restate)
and **5 (the parity fence, 2026-09-21)**. The ADR's own Status line is
the owner's to flip; implementation is complete.
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
· step 1 shipped v1.18.8 · steps 2 and 2.5 landed 2026-09-20, steps 3a
(web), 3a-sec, 3b (VSCode) and 4 on 2026-09-21, all on `bugfix/v1.19.3`,
no target release.

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
> not a shared file — see step 3. **ALL SIX ARE NOW GONE:**
> `_BUILTIN_SPECIAL_COMMANDS` + `_CLIENT_GATES` (step 1b),
> `web/shared/commands.js` and the `app.js` fallback catalog (step 3a),
> `commands.ts` (step 3b, same day), and the `_*_SUBCOMMANDS` tables
> (step 4, same day). Only `CommandSpec` — the intended single source —
> is left.
>
> **Second correction (2026-09-21, while doing step 4): there were SEVEN
> `_*_SUBCOMMANDS` tables, not six.** This file and the ADR both say
> six; the file held `_TOOLS_`, `_USAGE_`, `_CHECKPOINT_`, `_STATUS_`,
> `_THEME_`, `_TASK_` **and `_RUN_`** (the U3 one-off family, added after
> the count was taken). Five further static tables were NOT
> `_*_SUBCOMMANDS` and are still there by design — see step 4.

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

(The script above no longer runs: step 3a deleted `commands.js` and step
3b deleted `commands.ts`. There is no JS/TS roster left to diff — both
clients fetch `GET /commands`, so the only drift left to measure is
inside Python. Kept verbatim as the dated measurement it was.)

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

### 3. JS clients fetch at startup — split into 3a (web) and 3b (VSCode) — ✅ BOTH DONE (2026-09-21)

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
| `tests/test_shared_commands.py` | Retargeted, not deleted. Its web half is inverted into deletion fences (`commands.js` stays gone; `index.html` stops loading it; `app.js` has no catalog) plus fences on the replacement module. Its VSCode **parity** half now compares `commands.ts` against the **Python registry** instead of against `commands.js` — the old comparison stayed green while both JS copies drifted from Python. The `/run`·`/task`·`/token` gap is pinned as an explicit known-gap test that fails the day step 3b (or a hand patch) closes it — **it did, the same day; see §3b** |
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
silently. **Closed by 3a-sec below** — the pinned set is now empty.

#### 3a-sec. Sensitive subcommands — ✅ DONE (2026-09-21)

The leak the step-3a finding above recorded, closed with the machinery
step 3a built. **Pre-existing**, not introduced by 3a: someone had
mitigated it (prompt form, rotate warning) without closing it.

**The declaration.** `CommandSpec.sensitive_subcommands:
frozenset[str]` (default empty), validated at registration — every name
must be a declared subcommand, or `register()` raises a `ValueError`
naming the command, like the other `_validate_spec` rules. ADDITIVE:
`subcommands` keeps its `list[tuple[str, str]]` shape. `/token` declares
`{"set"}`, and it is the only command that declares anything (pinned, so
the day a second one appears a reviewer re-checks every sink).
`CommandFactory.roster()` gains `"sensitive": bool` on each subcommand
dict; `CompletionCommandInfo` carries the frozenset. **Version/ETag
semantics unchanged** — the flag rides on the existing payload.

**The helper.** `CommandFactory.redact_sensitive(text) -> str`, beside
the registry, pure and side-effect free. If `text` (optionally prefixed
by the `> ` echo marker) is a slash command whose name **or alias**
resolves to a spec with sensitive subcommands, and its first argument is
one of them **with a value after it**, everything from that value on
becomes a fixed mask (`••••`, never derived from the secret — a
length-preserving mask leaks the length).

**Decisions, made explicitly:**

- **Case-INSENSITIVE** on both the command name and the subcommand. Not
  cosmetic: the web dispatcher lowercases the command
  (`parts[0].toLowerCase()`) and `_handleTokenCommand` lowercases the
  verb, so `/TOKEN SET abc` really does store a token — a
  case-sensitive redactor would pass exactly that line through. The
  text KEPT is the original, unaltered.
- **Whitespace-tolerant.** Any run of whitespace (tabs included)
  separates the tokens, leading whitespace is ignored, and the kept
  prefix is byte-for-byte original; only the separator before the mask
  normalises to one space, so the output is deterministic.
  `/token\tset\tabc` -> `/token\tset ••••`.
- **A value is required.** `/token set` and `/token set   ` pass through
  unchanged — which is what keeps completion of `/token se` -> `set`
  working, on both the client and the server.
- **Never raises.** Non-`str` returns `""` (a sink handed a dict body
  must not 500); the regexes are token-based (`\S+`) so they are linear
  and cannot backtrack; the one defensive `except` fails CLOSED.

**Sinks found, and the disposition of each.** Server (defense in depth —
these protect stale web assets served from `~/.ppxai/web` and VSCode,
whose client half waits for 3b):

| Sink | Disposition |
|---|---|
| `POST /client-log` (`routes/config.py`) — the `> <input>` echo mirror, straight into `~/.ppxai/logs` | **The leak.** `message` goes through `redact_sensitive` before `log_client_event`. Redacted, not dropped: the masked line is still logged, so the fix costs no observability |
| `POST /complete` (`routes/completion.py`) — the composer buffer, per keystroke | A buffer redaction would change is answered with **no items**, and `complete()` is never called with it, so nothing derived from it is computed or echoed. (`complete()` returns `[]` for this buffer today anyway — the guard is the mechanism, and the test asserts the engine never sees the buffer rather than asserting the empty outcome) |
| `POST /command/{name}` (`routes/commands.py`) — `args_preview` | Already argument-free for a client-handled command (step 1b). Now redacted through the same helper for a SERVER-dispatched command that declares a sensitive subcommand — none exists today, which is exactly why the guard belongs here rather than being remembered later |
| `http.py` middleware (auth, activity, host validation) + the unhandled-exception handler | **Checked, no change needed.** None logs a request BODY; the exception handler logs `method + path` only. There is no generic body logger, so nothing captures these before the route runs |

Client (`ppxai/web/` only — `vscode-extension/` was untouched here; its
own sink table is in §3b):

| Sink | Disposition |
|---|---|
| The `> <input>` chat echo (`CommandDispatcher.dispatch`) — rendered AND mirrored to `/client-log` | Redacted via `_redactEcho` before either |
| `POST /complete` (`app.js::handleInputChange`) | Skipped once the buffer carries a value after a sensitive subcommand. `/token se` still completes to `set` — sensitivity needs content AFTER the flagged subcommand |
| Input history — `state.commandHistory` **and** `localStorage['ppxai-history']` (`app.js::sendMessage`) | Not written. ArrowUp cannot recall what was never stored |
| Already-persisted history from before this fix | Purged once, right after the roster lands (`_purgeSensitiveHistory`) — deliberately not before, or the fail-closed rule would wipe every slash command |
| `console.warn('dispatch called while already handling:', input)` | Redacted too. Devtools-only (nothing forwards `console` to `/client-log` — checked), but free |
| `showError` / `_explainMissingRoster` | **Already clean**: every message is built from the command NAME, never the args |
| `POST /command/<name>`, `POST /chat` (streaming commands) | Already covered by step 3a's roster gate — a client-dispatched command is never POSTed, and with no roster nothing is |

**The client-side rule lives in ONE place**: `CommandRoster.classify()`
in `web/shared/command-roster.js`, with `isSensitive()` / `redact()` on
top of it, and `CommandRoster.redactWithoutRoster()` for a page with no
roster INSTANCE at all. No client code anywhere names `/token` or `set`.

**FAIL CLOSED**, consistently with step 3a's dispatch gate: with no
roster loaded, the args of ANY slash command are treated as sensitive —
echo masked after the command name, `/complete` skipped, nothing
written to history. The command NAME is kept (it is not a secret and
the refusal message needs it), and a bare `/tok` is still completable,
so name completion survives. Plain chat is never touched in either mode.

**`_handleTokenCommand`'s inline warning reworded** to the new reality —
the value no longer leaves the page — while still recommending the
prompt form, which remains the only one that never puts the token on
screen or in a shoulder-surfable composer.

**Tests.**

| File | Disposition |
|---|---|
| `tests/test_sensitive_subcommands.py` | **New**, 89 tests. Spec validation (incl. the "flagged a subcommand on a spec that declares none" typo); `/token` declaring `set` and being the ONLY declaring command; roster + `CompletionCommandInfo` carrying it, alias entries included; the helper's full truth table — echo prefix, case, whitespace/tabs, alias, idempotence, fixed-length mask, ~25 never-raises fuzz cases, non-`str` inputs, a linearity check; and the three routes. Every security assertion is **MUTATION-VERIFIED** through a `no_redaction` fixture that neuters the helper: `/client-log` then leaks (the pre-fix behaviour, on demand), `/complete` then hands the engine the secret, and `/command/<name>`'s `args_preview` then carries it |
| `tests/test_web_sensitive_redaction_behavior.py` | **New.** Drives the REAL roster + dispatcher under Node: the JS truth table mirrors Python's line for line; the rule follows the DATA (flip `sensitive` in the payload and the answer flips); fail-closed with no roster; nothing raises on odd input; and the dispatcher's echo is redacted with and without a roster, with the `showSystemMessage` fake wired to a `/client-log` call log so the assertion is about the real sink. Two mutants — an unredacted echo, and a roster that fails OPEN — must both fail the harness |
| `tests/test_command_roster_endpoint.py` | `TestPayloadShape::test_field_types` — subcommand keys are now `{name, description, sensitive}` |
| `tests/test_web_command_dispatcher_v18_1.py` | Size fence 480 → 510 with the reason in its threshold history (`_redactEcho` + rationale; the rule itself lives in `command-roster.js`) |
| `tests/e2e/live-app.spec.ts` | `EXPECTED_ECHO_PATHS` is **empty** — the pinned leaking set `['/client-log','/complete']` is gone. New describe block against the real UI: the roster declares `set` sensitive; an inline `/token set SECRET` appears in NO request body or URL, is not in the rendered transcript (the masked echo is), is not in `commandHistory` or `localStorage`, is not recalled by ArrowUp, and DID store the token; the buffer is never sent to `/complete`; `/token se` still autocompletes to `set`. Mutation-verified by hand: with `_redactEcho` reverted, the run fails on `POST /client-log` carrying the raw secret |

**Still open after this step:** the VSCode CLIENT side. `chatPanel.ts`
echoes and dispatches `/token` itself and is not roster-driven until
step 3b, so an inline `/token set` typed in the VSCode panel can still
be echoed client-side. The SERVER-side redaction above already covers
its `/client-log` and `/complete` paths, which is the half that reaches
disk. **CLOSED by step 3b, same day** — see the sink table there.

#### 3b. VSCode — ✅ DONE (2026-09-21)

`vscode-extension/src/commandRoster.ts` (`CommandRoster`) fetches
`GET /commands?client=vscode` through a new
`HttpClient.getCommandRoster()`, caches it, resolves canonical names AND
aliases, and exposes the `classify/isSensitive/redact` rule — semantics
identical to web's `CommandRoster`, pinned against
`CommandFactory.redact_sensitive` case by case rather than restated.
`vscode-extension/src/commandRouter.ts` (`CommandRouter` +
`CLIENT_ACTIONS` + `LEGACY_INTERCEPTS`) routes on the roster's
`dispatch` field. **Neither module imports `vscode`** — the
`taskController.ts` IoC idiom — which is what lets the behavioural tests
compile the real TypeScript with the extension's own `esbuild` and drive
it under Node. `POST /command/{name}` bodies now carry
`client: "vscode"`.

`chatPanel.ts::handleSlashCommand` is three lines (route, catch). The
twelve-branch intercept chain and the `CHAT_SHAPED_TASKS` map are gone:

    CLIENT_ACTIONS = {
        'token.manage'   -> handleTokenCommand
        'task.controller'-> getTaskController().handle
        'run.controller' -> getRunController().handle
        'auto.loop'      -> handleAgentCommand
        'coding.stream'  -> handleCodingTaskCommand(ctx.name, ctx.args)
        'coding.convert' -> handleConvertCommand
        'preview.panel'  -> handlePreviewCommand
        'help.augment'   -> showHelp
    }

`coding.stream` is ONE action shared by six commands: the implementation
receives the CANONICAL name the roster resolved and passes it straight
through as the `task_type`. **`CHAT_SHAPED_TASKS`' mapping half turned
out to be the identity** — every entry was `['x', 'x']` — so nothing
had to be kept as local data. A side effect: the registered aliases
`/g`, `/gen`, `/d`, `/impl` reach the coding path for the first time;
the Map keyed on canonical names only and silently forwarded them to the
factory. An action the roster names with no implementation produces a
clear error and is **never** forwarded. `app.quit` never reaches the
table — `/quit` is gated to `clients={rich, textual}`, so it is not in
the 44 commands the server serves at `?client=vscode` at all.

**One deliberate behaviour change to know about:** `/help` now needs the
server. It used to render from the bundled catalog, so it worked with
the backend down; it is now `POST /command/help` behind the fail-closed
gate, like every other slash command. Plain chat is unaffected, and the
refusal names the likely cause.

**The five acknowledged-legacy intercepts stay, as an explicit named
baseline.** `LEGACY_INTERCEPTS = ['tools', 'checkpoint', 'context',
'ls', 'tree']` in `commandRouter.ts`, consulted AFTER the fail-closed
gate (so they are not an escape hatch), with a `DO NOT ADD TO THIS LIST`
comment. Per the owner's "do not bless debt" they get no
`client_action`. `tests/test_client_handled_commands_contract.py`
asserts the table holds **exactly** those five, that no command with a
declared `client_action` appears in it, and that no legacy name leaked
into the action registry — the shrinking baseline step 5 inherits.

**FAIL CLOSED**, as web, and the stakes are higher: the extension host
is a Node process with the developer's full privileges, and the VSIX
versions independently of the `ppxai-server` binary, so "newer client,
older server that 404s `/commands`" is an everyday state rather than an
edge case. No roster → retry once inline → refuse, naming version skew.
No hardcoded `/token` escape hatch. Plain chat is unaffected.

**Fetch lifecycle.** `initializeBackend()` awaits `roster.load()` as the
first thing after the connection is confirmed (before `setWorkingDir`),
so a command typed straight after connect cannot race it.
`updateServerStatus(false)` and the `stop` branch of
`handleToggleServer` call `roster.unload()` — the roster describes a
SERVER, and a reconnect may reach a different one. `/reload` refetches
via the `refresh_command_roster` side effect, added to
`sideEffectsHandler.ts` (which stays — it is a BEHAVIOUR mirror) as a
`refreshCommandRoster(version)` host call; the same version is a no-op.
`tests/test_session_end_workflows.py`'s connect/disconnect chain is
untouched.

**Sinks of the raw composer input, and the disposition of each**
(3a-sec's VSCode half, now closed). Enumerated across the extension
host, the webview and everything between them:

| Sink | Disposition |
|---|---|
| The webview transcript echo (`commandMessage`, posted by what is now `echoCommand`) | **Redacted** — `CommandRouter.route()` masks via the roster before the echo, fail-closed with none |
| `POST /complete` (`handleComplete`, one call per keystroke) | **Skipped** once the buffer carries a value after a sensitive subcommand. `/token se` still completes to `set` |
| The webview's ↑ history (`commandHistory` in `media/webview/main.js`) | **Purged.** `sendMessage()` pushes the raw line before the host sees it, so the host posts `forgetHistory` with that line and the webview drops matching entries. The webview holds NO copy of the rule — deliberately, so there is still one implementation |
| `vscode.setState` / `getState` (persisted webview state) | **None exist** — grepped; the history is an in-memory array that dies with the webview |
| `globalState` / `workspaceState` | **Checked, clean.** The only writer is `sessionsProvider.ts` (`ppxai.sessions`), which stores server-side session metadata, never composer input |
| `POST /client-log` | **Never receives raw input.** Every `logClientEvent` call site forwards a `systemMessage`/`error` the client PRODUCED (`getHandlerContext`, `wireUISubscriptions`, `CommandRenderer`'s host). The command echo is posted straight to the webview and is not mirrored. The server-side redaction from 3a-sec stays as defence in depth |
| The `ppxai HTTP` OutputChannel (`httpClient.ts`) | **Checked, clean.** It logs connection state, SSE event JSON, consent answers and agent lifecycle; `executeCommand` and `complete` log nothing |
| `console.*` in the extension host | **Checked, clean.** `commandRenderer.ts` warns with the result TYPE, `sideEffectsHandler.ts` with the KIND; no call carries user input |
| webview → host `postMessage` (`chat`, `complete`) | **Enumerated, unchanged.** In-process IPC inside the extension: not logged, not persisted, never networked, and the value is already in the composer DOM the message came from. Gating it would need the webview to carry the rule — a second roster |
| `POST /command/{name}` args | A client-dispatched command is never POSTed, and with no roster nothing is |
| SecretStorage `ppxai.apiToken` | **Kept** — that IS the token store, shared with the `ppxai.setApiToken` palette command |

`handleTokenCommand`'s inline warning is reworded to the new reality
(the value no longer leaves the client) while still recommending the
bare `/token set`, whose masked input box never puts the token on screen.

**`showHelp` now renders the SERVER's `/help`** and appends only the
keyboard shortcuts — see the correctness contract's item 3 above for
what it really did before, which was not what any comment claimed.

**The `/auto` bug web had is NOT present here.** Web's `_dispatchAgent`
POSTed a bare `/auto` to `/command/agent` (ADR 0011 renamed it with no
alias). VSCode's `handleAgentCommand` answers a bare `/auto` with a
usage error and never dispatches, so there was nothing to fix; the
behaviour is deliberately unchanged.

**No seventh roster.** `vscode-extension/media/webview/main.js` and
`styles.css` were checked for a command list of their own: the only
command literal in the webview is `'/context'`, a badge click that sends
that one command as chat. Autocomplete has been server-side since
v1.17.4.

**Tests.**

| File | Disposition |
|---|---|
| `tests/test_vscode_command_roster_behavior.py` | **New.** Compiles the REAL `commandRoster.ts` + `commandRouter.ts` + `sideEffectsHandler.ts` (its one `vscode` import aliased to a stub) with the extension's own esbuild into pytest's `tmp_path`, then drives them under Node against a call-logging fake backend and the REAL `CommandFactory.roster("vscode")` payload: all eight actions; six commands → one `coding.stream` with the resolved name; aliases (`/gen`→`generate`, `/cat`→`show`); routing flips when the ROSTER flips; server dispatch carries `client:"vscode"`; unknown action → error + no POST; the legacy five still intercepted; **no roster → `/token set <secret>` issues nothing but the roster retry, stores nothing, masks the echo and purges the history**; `unload()` reverts to fail-closed; `refresh_command_roster` reaches the host; a failed refresh keeps the working roster. The redaction truth table is compared case by case against `CommandFactory.redact_sensitive` rather than restated. Three mutants (gate removed, client branch bypassed, `classify` failing open) must all FAIL the harness |
| `tests/test_client_handled_commands_contract.py` | Part B's VSCODE half rewritten (web half untouched). The old invariant — `command === 'token'` precedes `dispatchFactoryCommand(` — deliberately no longer exists. New helpers, each mutation-verified in the same file: the fail-closed gate precedes every dispatch path in `route()`; the client-dispatch branch precedes (and returns before) the factory fallthrough; no per-name escape hatch survives in `chatPanel.ts` (with the plan's own `grep -v subcommand` exclusion); the action registry implements every action Python declares for vscode (read off `iter_completion_specs()`); and `LEGACY_INTERCEPTS` holds exactly the five |
| `tests/test_shared_commands.py` | Retargeted again. Its VSCode half inverts into deletion fences (`commands.ts` stays gone, nothing imports it, the barrel stops re-exporting it) plus drift fences on the replacement (no hardcoded `'/name'` literals in either new module, no `vscode` import, aliases resolved from the `aliases` FIELD). The known-gap test for `/run`·`/task`·`/token` — written in 3a to fail the day 3b landed — did exactly that and is replaced by the positive assertion that the roster serves all three to vscode |
| `tests/test_vscode_step5b2_dispatcher.py` | Retargeted. `CHAT_SHAPED_TASKS` fences → the Python declaration (`coding.stream` on all six, `coding.convert` on `/convert`, `auto.loop` on `/auto`) plus the registry line that passes `ctx.name`. `handleSlashCommand` shape fences → the `PanelCommandOps` wiring. New: `/help` must now actually call the factory. The <3000-line fence was DELIBERATELY NOT raised (the registry lives in `commandRouter.ts`); the threshold history says so |
| `tests/test_vscode_task_controller.py` | `TS_COMMANDS` (deleted file) → `TS_ROUTER`; the three "routed before factory dispatch" fences → the registry binding + the Python declaration, since branch order is no longer what carries the guarantee |
| `tests/test_vscode_step5a_helpers.py` | `refresh_command_roster` added to both side-effect kind sets (the VSCode dispatcher's, and the web↔VSCode parity set) |
| `tests/test_session_end_workflows.py`, `tests/test_vscode_step5c_state_sync.py`, `tests/test_vscode_visibility_reanchor.py`, `tests/test_help_command_reconciliation.py`, `tests/test_preview.py` | **Assessed, unchanged** — none reads the deleted catalog or the intercept chain. The connect/disconnect workflow (`ppxai.startServer`/`stopServer`/`toggleServer`/`serverStatus`) is untouched by design |

**Not verified, and honestly so:** no real VSCode extension host ran.
What IS verified is `npm run compile` (tsc + esbuild), the Node
behavioural tests against the real compiled modules, the source-text
fences, and the full Python suite. What is NOT is real webview
interaction, SecretStorage, and the side-effect refetch in a live host.
The manual smoke list is in the step-3b report.

### 4. Derive, don't restate — ✅ DONE (2026-09-21)

Completion's subcommand tables read the spec, and `engine/completion.py`
stopped importing `CommandFactory` — the layer inversion and the
`engine → commands → engine` package cycle closed as a side effect.

**Acceptance, met:**
`grep -rnE "from \.\.commands|from ppxai\.commands|import ppxai\.commands" ppxai/engine/`
returns nothing — checked across the whole engine package, function-level
imports included. It was the only such edge; no other was found.

**The design decision: DATA IN, NOT A PROTOCOL.** An earlier draft (and
the ADR's own §Decision) had completion hold a `CommandRegistryProtocol`
collaborator inside a new `CompletionService` in a new top-level
`ppxai/completion/` package. **None of that was built, and none of it is
needed** — steps 1–2 removed the reason for it. `CommandFactory.roster(client)`
already returns PLAIN DATA: one entry per canonical command with
`aliases`, `hidden` and `subcommands`, already filtered by `client_sees`.
There is no collaborator left to abstract; a Protocol would only describe
"an object that can hand me a list of dicts", which is a list of dicts.

So `complete()` gained one keyword argument and lost one:

    def complete(buffer, cursor=-1, *, roster, working_dir=None,
                 current_provider=None, tool_names=None, agent_runs=None)

- `roster` is **required and keyword-only**, typed
  `list[dict[str, Any]] | None`: whatever
  `CommandFactory.roster(client)["commands"]` yields. It has **no
  default** on purpose — with only three callers, a forgotten roster
  would be a silently empty dropdown that no test would notice, while a
  missing argument is a `TypeError` naming the call site. Passing `None`
  or `[]` is legitimate and means "no registry": no slash-command or
  subcommand completions, while path and `@file` completion still work.
- **`client` is GONE.** With the roster arriving already filtered, a
  client id inside completion could only disagree with the data it was
  handed. `_gate_for`, `_client_allows` and the `client_sees` import went
  with it: gating is now structural — a command the client may not see is
  simply not in the list. The fail-OPEN semantics for `client=None`
  survives unchanged end to end, because the CALLER passes
  `roster(None)`, which is the whole catalog
  (`tests/test_client_handled_commands_contract.py`, Part A).
- **No fallback.** There is no `roster=None` branch that imports
  `CommandFactory`, no lazy import, no `sys.modules` lookup. A fallback
  would be the same edge behind a branch nothing exercises.

**Which tables moved, and which did not.** Seven (not six) tables were
first-level subcommand rosters and moved onto their command's
`CommandSpec(subcommands=[...])`, order and descriptions byte-identical,
using `/token` (step 1b) as the pattern:

| Table | Rows | Now declared in |
|---|---|---|
| `_TOOLS_SUBCOMMANDS` | 10 | `commands/tools.py` |
| `_USAGE_SUBCOMMANDS` | 5 | `commands/tools.py` |
| `_CHECKPOINT_SUBCOMMANDS` | 6 | `commands/agent.py` |
| `_STATUS_SUBCOMMANDS` | 3 | `commands/system.py` |
| `_THEME_SUBCOMMANDS` | 2 | `commands/system.py` |
| `_TASK_SUBCOMMANDS` | 8 | `commands/task.py` |
| `_RUN_SUBCOMMANDS` | 6 | `commands/task.py` |

Five static tables stayed in `engine/completion.py`, and NOT because they
were missed — the flat `list[tuple[str, str]]` shape cannot express them
without conflating two argument positions (they would then be offered as
first-level subcommands and published as such in `GET /commands` and
`/help`):

| Stayed | Why |
|---|---|
| `_USAGE_DISPLAY_MODES` (4), `_CHECKPOINT_BACKENDS` (4), `_EMOJI_OPTIONS` (2), `_TASK_RESPOND_ANSWERS` (2) | **second-level** arguments (`/usage show <mode>`, `/checkpoint backend <name>`, `/theme emoji <on\|off>`, `/task respond <id> <answer>`). Expressing them needs a nested argument schema — step 1's "how are argument kinds expressed" question, still open |
| `_THEME_NAMES` (13) | first-level, but a restatement of a RUNTIME registry (`ppxai/tui/themes/themes.py` + `rich/themes.py`), not of the command declaration. Moving it to the spec would freeze a third copy into the roster; the real fix points at the theme registry, and `engine → tui` would be a NEW inversion |
| `_TASK_ID_VERB_STATUSES`, `_PATH_ARG_COMMANDS`, `_CONTEXT_PROVIDERS` | not subcommands at all: a verb→status routing map for live run ids, a path-argument kind table, and the `@`-provider list |

Genuinely dynamic suggestions were untouched and stay behaviour: run ids
(`/task get <id>`), model ids, provider ids, tool names, file paths.

**Side benefit, confirmed:** web and VSCode now receive subcommands for
all eight declaring commands through `GET /commands` — they used to get
`/token`'s only.

**`/help` needed no change, and nothing else restates command metadata on
the Python side.** `/help` has been generated from the registry since
step 1b (`CommandFactory.generate_help`) and `/help <cmd>` from
`get_command_help`; neither renders `subcommands`, so moving the tables
changed no help output. **Follow-up, deliberately not taken here:** now
that eight commands declare subcommands, `/help <cmd>` COULD list them.
That is a visible output change to a surface with its own tests, and
`/token` has declared subcommands since step 1b without showing them, so
it is a separate, deliberate decision rather than a rider on this step.

**Fences.** `TestEngineCompletionStaysALeaf` is **deleted** — its own
failure message said to, and with the upward import gone there is nothing
left to be a leaf about. It is replaced, in the same file and style as
`TestConfigDoesNotImportEngine`, by
`tests/test_no_new_lazy_imports.py::TestEngineImportsNoCommands`: **no
module under `ppxai/engine/` imports `ppxai.commands`**, module scope or
function level, held at ZERO, guards-first.

**Mutation-verified, and the result is worth recording** because it
differs from the other two fences: restoring the deleted module-scope
import in `engine/completion.py` **does nothing visible** — `pytest
--collect-only` still collects all 6,285 tests, `import
ppxai.engine.completion` still succeeds in a fresh interpreter, and the
completion suites stay green. Only the new fence fails. (For
`TestConfigDoesNotImportEngine` and for the retired leaf guard, the
module-scope mutation was LOUD: a collection-time `ImportError`.) A
function-level mutation fails the new fence and `TestNoNewLazyImports`,
and nothing else. So this rule is invisible in production and exists only
as long as the test does.

**Tests.**

| File | Disposition |
|---|---|
| `tests/test_completion_provider.py` | Every existing assertion UNCHANGED, via a module-level `complete(buffer, cursor, *, client=None, **kw)` helper that does what the three real callers do (fetch `roster_for(client)`, pass it in) — so the behaviour comparison is honest rather than rewritten. NEW: no `_*_SUBCOMMANDS` table survives in the source (regex fence, guard tested first); each migrated command's offered subcommands and DESCRIPTIONS equal its `CommandSpec.subcommands` (compared against the spec, never a copy); a subcommand added to the DATA flows through; second-level tables still answer; no duplicate subcommand within a command; absent/empty roster offers no slash commands but still completes paths and `@file` refs; `roster` is required (`TypeError`); and the three callers pass their correct client id — source-text for all three plus a behavioural check that Rich's and Textual's real completers offer `/tools` and not `/token` |
| `tests/test_client_handled_commands_contract.py` | Part A retargeted, Part B untouched. `_client_allows`/`_gate_for` no longer exist, so the unit-level gate is asked of `client_sees` + the roster's CONTENTS, and the liveness proof (a `monkeypatch` on `_gate_for`) becomes "flip the DATA and the answer flips" — the idiom the web/VSCode behavioural suites already use. The `client=None` fail-open pin is unchanged end to end |
| `tests/test_client_handled_dispatch.py` | Same one-line helper; its `/token` assertions are unchanged, including "subcommands come from the spec" — true for all eight now |
| `tests/test_no_new_lazy_imports.py` | Guard 2 replaced (above) |
| `tests/test_command_spec_schema.py` | Prose only — a comment describing where `KNOWN_CLIENTS` ids are measured |

### 5. Parity fence — ✅ DONE (2026-09-21)

`tests/test_command_parity_fence.py` (128 tests). A test that fails when
a client implements a command action the registry does not declare, when
the registry declares one a client does not implement, or when a
hand-written roster reappears anywhere. The rosters drifted silently for
months because **nothing compared them**; this is the comparison.

**What each assertion reads, and how.** Every one reads the PYTHON
declaration and compares it against the REAL client source — nothing is
restated by hand except the two named baselines below.

| # | Assertion | Read from |
|---|---|---|
| 1 | **Action coverage, both directions, per client** — every action Python declares for a client is implemented by it; every key in a client's registry is an action Python declares for that client; every key is in `CLIENT_ACTIONS` | web: `CommandDispatcher.CLIENT_ACTIONS` (brace-aware object-key extractor over `command-dispatcher.js`); vscode: `CLIENT_ACTIONS` in `commandRouter.ts` (same extractor, plus a **compiled-module cross-check** — esbuild + Node, `Object.keys()` off the real bundle); rich/textual: their `CommandFactory.names_for_client_action("…")` call sites |
| 2 | **No undeclared intercepts** — zero per-name branches in the web dispatcher and in `chatPanel.ts`; `LEGACY_INTERCEPTS` is the ONLY name-keyed table in `commandRouter.ts` (its four exported tables are pinned by name) and matches `LEGACY_HANDLERS`; the legacy baseline may only shrink; no command with a `client_action` sits in it | regex over comment-stripped source, with the plan's own `grep -v subcommand` caveat encoded as `(?:^\|[^A-Za-z])command === '…'` and regression-tested |
| 3 | **No surviving hand-written roster** — every deletion in the completeness table below fenced as ABSENT, plus a GENERIC detector | see §The generic catalog detector |
| 4 | **Side-effect kind coverage**, both directions and web↔vscode | DERIVED from `SideEffectKind.all_kinds()`; web's `SideEffectsHandler._handlers` keys, VSCode's `case KIND.X:` resolved through the exported `KIND` table |
| 5 | **Roster self-consistency** — for every id in `KNOWN_CLIENTS`, `CommandFactory.roster(client)` names no `dispatch == "client"` action that client does not implement, and none with no action at all | the real `roster()` payload, against assertion 1's implemented sets |

**The extractors are the fragile part, so the fragility is loud.**
Every one is self-tested on synthetic input BEFORE anything uses it,
including the three traps this work actually hit: an apostrophe inside a
`//` comment opening a string that eats the file; a template literal's
`${…}` unbalancing a brace counter; `subcommand === 'clear'` matching a
`command === '…'` pattern (the mistake that inflated VSCode's intercept
count from 12 to 16). A **fourth** trap was found while writing the
fence and is now guarded too: `String(s).replace(/[&<>"']/g, …)` in
`web/shared/side-effects.js` holds BOTH quote characters inside a REGEX
literal — read naively, that `"` opens a string that runs for a hundred
lines, and the handler table came back four entries short **with no
error**. The fence therefore has ONE JS lexer (`js_spans`) that knows
comments, strings, template literals and regex literals, and every
extractor is built on it. Every extractor also has a POSITIVE CONTROL
against the real file: "0 actions found" is an error, never parity.

**Where the real compiled module can be read, it is.** `commandRouter.ts`
imports no `vscode`, so the fence bundles it with the extension's own
esbuild and reads `Object.keys(CLIENT_ACTIONS)` and `LEGACY_INTERCEPTS`
under Node, then asserts the regex agrees (`TestRegexAgreesWithThe
CompiledModule`). Web's modules are plain CommonJS, so they are simply
`require`d (`TestWebRegexAgreesWithTheRealModule`). Both cross-checks
skip without Node; the regex path always runs, so the fence has no
environment hole. **If the two ever disagree, trust the compiled module
and fix the regex.**

#### The seventh roster — found on the PYTHON side, fixed here

Step 4's report flagged three things this step had to close:

- **`ppxai/rich/ui.py::display_welcome()`** was a LIVE hand-written
  ~30-command list with its own usage strings and descriptions,
  rendered at Rich startup (`rich/main.py:430`) — and already drifted:
  **18 registered commands were missing from it** (`/attach`, `/cd`,
  `/checkpoint`, `/config`, `/debug-log`, `/doctor`, `/edit`, `/keys`,
  `/ls`, `/preview`, `/preview-log`, `/pwd`, `/reload`, `/run`,
  `/task`, `/terminal`, `/theme`, `/tree` — i.e. every command added
  since roughly v1.17), several descriptions no longer matched the
  spec (`/autoroute`, `/copy`), and it advertised `/tools help editing`
  and three `/status` + three `/context` subcommands that the registry
  now publishes as `subcommands` instead. It is now DERIVED from
  `CommandFactory.roster("rich")["commands"]`, grouped by `category`,
  keeping the Panel/Markdown look. The command list is the registry's;
  only the file-editing consent/safety prose (which names exactly ONE
  command) is still written out.

  **It takes the roster as DATA — a required, keyword-free positional —
  exactly as step 4 did for `complete(roster=…)`, and for a hard
  reason, not for symmetry.** `ppxai/rich/ui.py` CANNOT import
  `ppxai.commands`: `ppxai/commands/__init__.py` imports `.handler`,
  which imports `..rich.ui`, so a module-scope import there is a
  genuine circular-import failure (verified: `ImportError: cannot
  import name 'console' from partially initialized module
  'ppxai.rich.ui'`), and the project bans lazy imports and
  `TYPE_CHECKING`. `rich/main.py` already held `CommandFactory` and
  already called `roster("rich")` for completion, so the caller pays
  nothing. No default: a forgotten roster is a `TypeError` naming the
  call site rather than a silently empty welcome screen.

- **`ppxai/rich/ui_components.py::render_welcome()`** — a second,
  differently-worded welcome roster (13 commands). **Zero callers**,
  including tests (verified across `ppxai/`, `tests/` and `scripts/`).
  **Deleted.**

- **`"q"`.** `ppxai/tui/app.py` intercepted `cmd in ("quit", "q",
  "exit")` and `ppxai/commands/handler.py` the literal pair
  `["/quit", "/exit"]`. Both literals are now DERIVED:
  `CommandFactory.names_for_client_action("app.quit")` (new classmethod
  — it asks for the ACTION, which is what the client implements, and
  gets back the canonical name plus aliases). Textual keeps ONE named
  legacy extra, `TEXTUAL_LEGACY_QUIT_NAMES = frozenset({"q"})`,
  commented at its definition and carried in the fence as a single-row
  shrinking baseline. **This is an OPEN OWNER DECISION and step 5
  deliberately did not make it** — see §Open owner decisions.

#### The generic catalog detector

Assertion 3's second half: the roster nobody thought to name. It scans
`ppxai/web/**/*.js` (minus `lib/`), `vscode-extension/src/**/*.ts`,
`vscode-extension/media/**/*.js` (minus minified vendor) and
`ppxai/**/*.py` (minus `ppxai/commands/`) for a **literal** — an
array/object literal in VALUE position, or a single non-docstring
string — naming **N or more distinct registered commands with a leading
slash**.

**N = 6, measured rather than guessed.** After this step's deletions the
whole scanned tree yields exactly two literals above three:
`STREAMING_COMMANDS` at 8 and a quick-command button block in
`web/app.js` at 4. The catalogs this record deleted measured 28
(`rich/ui.py`'s welcome), 13 (`render_welcome`), ~30 (`app.js`'s
`slashCommands`) and 31 (`commands.ts`), so 6 has clear air on both
sides.

Three tuning decisions, each forced by a measurement and each with a
regression test:

- **Value position only.** Without it an entire `class
  ChatViewProvider { … }` body read as one literal naming 23 commands,
  which would have pushed N into uselessness. A `{`/`[` counts only when
  it follows one of `=(,:[{|&?`, so class bodies, function bodies and
  `if (…) {` are excluded.
- **Command tokens, not substrings.** `/command/clear`, `/v1/tokens`
  and `/models` must not read as commands; without the lookarounds
  `api-client.js` scored 17 and `httpClient.ts` 20. Single-character
  names (`/c`, `/s`, `/g`) are excluded outright as unusable noise.
- **Docstrings are not catalogs.** `engine/completion.py`'s module
  docstring explains at length which tables step 4 deleted, and naming
  them is a record, not a roster. A NON-docstring string constant is
  still scanned — that is exactly the shape the Rich welcome had.

**One exemption, named with its reason**
(`CATALOG_EXEMPTIONS`): `STREAMING_COMMANDS` in
`command-dispatcher.js` (8 names) classifies commands whose RESPONSE is
the chat stream — a behaviour classification, not command metadata, and
the roster carries no `chat_shaped` field to derive it from. The
exemption is itself fenced: if the literal disappears, the row must be
deleted. Folding chat-shaped-ness into the roster would remove it, and
is recorded in §Open owner decisions rather than taken here.

#### Side-effect coverage: the hardcoded sets are gone

`refresh_command_roster` was added to `SideEffectKind` in step 2 and no
client noticed, because both drift fences hardcoded their own expected
sets. **Retargeted, not deleted** — a reader editing `side-effects.js`
looks in `test_web_shared_modules.py`, so that row stays, now iterating
`SideEffectKind.all_kinds()`. Same for both rows in
`test_vscode_step5a_helpers.py` (the per-client one and the web↔VSCode
parity one, which compared both clients against a THIRD hand-written
list). The full both-directions comparison lives in the new fence.

**That retarget immediately found a live drift:**
`test_web_shared_modules.py`'s hardcoded set was missing **`prompt_text`**
— web has always implemented it, so the fence had simply stopped
covering one kind. Nothing was broken; the guard was.

#### The two shrinking baselines, and how to shrink them

| Baseline | Today | Shrink it by |
|---|---|---|
| `LEGACY_INTERCEPT_BASELINE` | `tools`, `checkpoint`, `context`, `ls`, `tree` | migrating the command to factory routing, deleting its row from `LEGACY_INTERCEPTS` + `LEGACY_HANDLERS` in `commandRouter.ts`, **and** deleting the row here. A removed entry FAILS until the baseline row goes too, so this file stays a record of the cleanup rather than a wish-list |
| `TEXTUAL_LEGACY_QUIT_BASELINE` | `q` | registering `q` as an alias of `/quit` (owner decision — see below), deleting `TEXTUAL_LEGACY_QUIT_NAMES` from `ppxai/tui/app.py`, and emptying this baseline |

Both directions fail. Adding to either fails with a message saying what
to do instead ("declare a `client_action`"; "this is an open owner
decision").

#### Mutation table

Every assertion was verified by mutating the real tree, running the
fence, and reverting — never leaving an edit behind.

| Mutation | Test that failed |
|---|---|
| orphan `'ghost.action'` added to web's `CLIENT_ACTIONS` | `test_every_implementation_is_declared[web]` + `test_every_implementation_is_in_the_vocabulary[web]` |
| web's `token.manage` renamed away | `test_every_declared_action_is_implemented[web]` + the two orphan checks + `test_no_client_dispatch_entry_names_an_unimplemented_action[web]` |
| `'newthing'` added to `LEGACY_INTERCEPTS` | `test_the_legacy_baseline_has_not_grown` + `test_the_legacy_handlers_match_the_legacy_list` |
| `'tree'` removed from `LEGACY_INTERCEPTS`, baseline row left | `test_the_legacy_baseline_has_no_stale_rows` + `test_the_legacy_handlers_match_the_legacy_list` |
| VSCode's `preview.panel` row deleted | `test_every_declared_action_is_implemented[vscode]` + `test_no_client_dispatch_entry_names_an_unimplemented_action[vscode]` |
| web's `prompt_text` handler renamed | `test_every_python_kind_is_handled[web]`, `test_no_client_handles_a_kind_python_does_not_declare[web]`, `test_the_two_clients_handle_the_same_kinds` — **and both retargeted fences** |
| a 7-command catalog prepended to `app.js` | `test_no_new_catalog_anywhere_in_the_tree` |
| a second legacy quit name added to `TEXTUAL_LEGACY_QUIT_NAMES` | `test_the_textual_quit_baseline_matches_the_source` |
| Textual's quit intercept re-spelled as a literal | `test_neither_tui_spells_the_quit_names_out` + `test_every_declared_action_is_implemented[textual]` + the positive control `test_every_client_implements_at_least_one_action[textual]` |
| `if (cmd === '/token')` re-added to the web dispatcher | `test_web_has_no_per_name_branch` |
| the hand-written Rich welcome restored | `test_the_rich_welcome_is_derived_not_written` + `test_no_new_catalog_anywhere_in_the_tree` |
| `_THEME_SUBCOMMANDS` reintroduced in `engine/completion.py` | `test_no_subcommand_table_survives[_THEME_SUBCOMMANDS]` + `test_no_subcommand_table_by_any_name` |

**Tests.**

| File | Disposition |
|---|---|
| `tests/test_command_parity_fence.py` | **New**, 128 tests. Guards (13 extractor self-tests incl. the four traps) → positive controls → the five assertions → the two compiled-module cross-checks → in-file mutation verification |
| `tests/test_consumer_import_surface.py` | **New**, 8 tests (~18s, subprocess import closure). Pins what step 4 bought for an out-of-repo consumer: importing the v1 gateway surface or `ppxai.engine.completion` loads **zero** `ppxai.commands` modules (both closure tiers measured at 77 modules). Positive control proves the probe can see a `ppxai.commands` import when there is one |
| `tests/test_web_shared_modules.py` | `test_handles_every_v18_1_kind` → `test_handles_every_kind`, derived from `SideEffectKind.all_kinds()`. Found the missing `prompt_text` |
| `tests/test_vscode_step5a_helpers.py` | Both hardcoded kind lists (per-client and web↔VSCode) derived the same way |
| `tests/test_client_handled_commands_contract.py`, `tests/test_shared_commands.py`, `tests/test_session_end_workflows.py` | **Assessed, unchanged.** The contract file's per-client action checks are the miniature this fence generalises; they stay as the place a reader of the dispatch ORDER looks |

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
   appear exactly once.

   **AND IN VSCODE, step 3b (2026-09-21) — where it was WORSE than this
   item described.** The row above (and every comment in `chatPanel.ts`)
   said VSCode's `showHelp` was "factory output + VSCode shortcuts". It
   was not: it called `generateHelpText()`, which rendered the
   hand-written 31-entry `shared/commands.ts` catalog, and **never called
   the factory at all**. So VSCode `/help` showed a roster missing
   `/run`, `/task`, `/token` and the nine commands the ADR's own table
   lists, then appended a hardcoded "Agent platform (client-side,
   experimental)" block naming exactly the three the catalog lacked —
   mislabelling `/run` and `/task`, factory-registered since T8b, as
   client-side shims. `showHelp` now renders
   `POST /command/help` with `client:"vscode"` and appends only the
   keyboard-shortcut section. Pinned by
   `tests/test_vscode_step5b2_dispatcher.py::TestHandleSlashCommandShape::
   test_help_now_actually_calls_the_factory`. The finding as it stood:

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

   **EXTENDED AND CLOSED FOR WEB in step 3a-sec, AND FOR VSCODE in step
   3b (both 2026-09-21).** The
   contract above was only ever about the DISPATCH path; the inline form
   leaked on two paths that run before dispatch is consulted (the
   `> <input>` echo -> `POST /client-log` -> `~/.ppxai/logs`, and the
   composer buffer -> `POST /complete`), which is why the warning existed
   at all. **The inline form no longer leaks on web.** Python declares
   `sensitive_subcommands={"set"}` on `/token`; the roster publishes
   `sensitive` per subcommand; `CommandRoster.isSensitive/redact` (the ONE
   client implementation — no client names `/token` or `set`) masks the
   echo, suppresses the `/complete` call and keeps the line out of the
   input history; and `CommandFactory.redact_sensitive` re-redacts at
   every server sink. The warning is reworded accordingly and still
   recommends the prompt form. **The VSCode CLIENT half was CLOSED by
   step 3b the same day** — `CommandRoster` (the TypeScript port of the
   same rule, pinned case by case against `redact_sensitive`) masks the
   webview echo, skips `POST /complete`, and purges the raw line from
   the webview's ↑ history; the full sink enumeration, including the
   sinks that turned out to be clean already (`/client-log`, the
   OutputChannel, `globalState`, and the absence of any
   `vscode.setState`), is in §3b. See §3a-sec for the web sink table and
   the shared fail-closed rule.

   Aliases need no schema work: `CommandSpec.aliases` exists, with
   resolution in `CommandFactory.get()` and publication via `iter_completion_specs()`
   (`is_alias` / `canonical`). `/exit` as an alias of `/quit` is native.

**Deletions that prove the migration is complete** — if any survives, a
second roster still exists. **All of them are done as of 2026-09-21**;
`CommandSpec` is the only declaration left. **Step 5 fences EVERY row
below as permanently absent** (`tests/test_command_parity_fence.py::
TestNoSurvivingHandWrittenRoster`), so this table is now executable
rather than aspirational — including a GENERIC detector for the roster
nobody thought to name:

| Deletion | Status |
|---|---|
| `_BUILTIN_SPECIAL_COMMANDS` + `_CLIENT_GATES` (`engine/completion.py`), and `_TOKEN_SUBCOMMANDS` with them | ✅ DONE — step 1b, 2026-09-20 |
| `_appendExperimentalHelp()` (`command-dispatcher.js`) and the `/help` intercept that existed only to call it | ✅ DONE — step 3a, 2026-09-21 |
| the inline fallback catalog (`app.js:199`, `this.slashCommands`) | ✅ DONE — step 3a |
| `web/shared/commands.js` in full — including the alias entries restated as standalone commands (`/cat`, `/sh`, `/term`) | ✅ DONE — step 3a; `CommandRoster.resolve()` reads the `aliases` FIELD |
| the five hardcoded `if (cmd === '/…')` intercepts in `command-dispatcher.js` | ✅ DONE — step 3a; routing is the roster's `dispatch` field. Fenced by `assert_web_has_no_per_name_escape_hatch` |
| `vscode-extension/src/shared/commands.ts` in full — 31 entries, plus `generateHelpText`, `SLASH_COMMANDS`, `parseCommand`, `isSlashCommand`, `AI_FORWARDED_COMMANDS` — and `chatPanel.ts`'s twelve intercepts + the `CHAT_SHAPED_TASKS` map | ✅ DONE — step 3b, 2026-09-21; routing is the roster's `dispatch` field. Fenced by `assert_vscode_has_no_per_name_escape_hatch` |
| the six `_*_SUBCOMMANDS` tables (`engine/completion.py`) | ✅ DONE — step 4, 2026-09-21. There were **seven** (`_RUN_SUBCOMMANDS` post-dated the count); all seven are gone, moved onto `CommandSpec.subcommands`. Five NON-`_*_SUBCOMMANDS` static tables stay by design (second-level arguments + the theme-name restatement) — see step 4 |
| `from ..commands.factory import CommandFactory` (`engine/completion.py:48`), and the `client` parameter of `complete()` with it | ✅ DONE — step 4; `grep -rnE "from \.\.commands\|from ppxai\.commands\|import ppxai\.commands" ppxai/engine/` is empty. Fenced at zero by `tests/test_no_new_lazy_imports.py::TestEngineImportsNoCommands`, which REPLACES the retired `TestEngineCompletionStaysALeaf` |
| `ppxai/rich/ui.py::display_welcome()`'s hand-written ~30-command list — the SEVENTH roster, on the Python side, rendered at Rich startup and 18 commands out of date | ✅ DONE — step 5, 2026-09-21; DERIVED from `CommandFactory.roster("rich")["commands"]`, handed in as plain data by `rich/main.py` |
| `ppxai/rich/ui_components.py::render_welcome()` — a second, differently-worded welcome roster (13 commands), **zero callers** | ✅ DONE — step 5; deleted outright |
| the literal quit names in the two TUI intercepts (`("quit", "q", "exit")`, `["/quit", "/exit"]`) | ✅ DONE — step 5; both derive from `CommandFactory.names_for_client_action("app.quit")`. ONE named legacy extra remains (`"q"`, Textual only) as a recorded owner decision |
| ANY new literal catalog, anywhere | ✅ FENCED — step 5's generic detector (N = 6 distinct registered commands in one literal), with one named, self-fencing exemption |

Not a deletion and deliberately so: `web/shared/side-effects.js` stays —
it is a BEHAVIOUR mirror (ADR 0007 §Which mirrors can go), and step 3a
ADDED a handler to it (`refresh_command_roster`). Step 5 holds it in
line the way that section prescribes: a parity fence reading the
Python-owned vocabulary (`SideEffectKind.all_kinds()`), in BOTH
directions and across both clients.

## Open owner decisions

Collected here at the close of step 5 — everything this record
deliberately did NOT decide. None blocks anything; each is a visible
behaviour or schema change that wants an owner, not a refactor.

1. **`/q` in Textual** (step 5). `ppxai/tui/app.py` accepts `/q`; it is
   not a registered alias, so completion, `/help` and `GET /commands`
   do not know it exists, and Rich does not accept it. **Registering it**
   makes it appear in Rich's completion too; **removing it** breaks a
   shortcut Textual users have. Held as the single-row baseline
   `TEXTUAL_LEGACY_QUIT_BASELINE` so the choice is recorded rather than
   hidden in a tuple literal.
2. **Should `/help <cmd>` list subcommands?** (step 4). Eight commands
   declare `subcommands` now, and neither `generate_help` nor
   `get_command_help` renders them — `/token` has declared them since
   step 1b without showing them. It is a visible output change to a
   surface with its own tests.
3. **The second-level "argument kinds" schema** (step 1, still open).
   Five static tables stayed in `engine/completion.py` because the flat
   `list[tuple[str, str]]` shape cannot express a SECOND argument
   position (`/usage show <mode>`, `/checkpoint backend <name>`,
   `/theme emoji <on|off>`, `/task respond <id> <answer>`) without
   publishing them as first-level subcommands in `GET /commands` and
   `/help`. `_THEME_NAMES` is a different case again: a restatement of a
   RUNTIME registry (`tui/themes/themes.py`), where the real fix points
   at the theme registry and `engine -> tui` would be a NEW inversion.
4. **Fold chat-shaped-ness into the roster** (step 5). Web's
   `STREAMING_COMMANDS` (8 names) is the one literal the generic
   catalog detector exempts. A `chat_shaped` field on `CommandSpec`
   would delete it — a schema change to a published payload, so it is
   its own decision.
5. **`GET /schema/app-state` has no consumer** (ADR 0007
   §Follow-up, out of scope here). The endpoint exists
   (`server/routes/schema.py:32`) and neither JS client calls it, while
   both keep hand-written mirrors pinned by cross-language sentinel
   tests. It is the command-roster problem one stage further along, and
   steps 3a/3b built exactly the fetch-at-startup machinery it would
   reuse. Deliberately not folded in: it touches the sentinel tests and
   the `state_sync` contract.
6. **Flipping ADR 0007 to Accepted/Implemented.** All five steps are
   done; the Status line is the owner's, not this work's.

## Hybrid commands — dispatch routing becomes data

Measured 2026-09-20. "Do I POST this to `/command/<name>` or handle it
here?" is a hardcoded `if`-chain in each JS client, and the chains differ:
**web intercepts 5 commands** (`command-dispatcher.js`), **VSCode 12**
(`chatPanel.ts:1140-1220`). Nothing records which client handles what.

> **Update (2026-09-21).** Both chains are gone — step 3a for web, step
> 3b for VSCode, each replaced by the roster's `dispatch` field plus a
> `client_action` → implementation registry. The counts to re-measure
> are now `0` and `0`; the second grep's target moved (`chatPanel.ts` has
> no `command === '…'` left, and the five acknowledged-legacy intercepts
> live in the named `LEGACY_INTERCEPTS` table in
> `vscode-extension/src/commandRouter.ts`).

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

> **The baseline now EXISTS, in code (step 3b, 2026-09-21).**
> `LEGACY_INTERCEPTS` in `vscode-extension/src/commandRouter.ts`, with
> `LEGACY_HANDLERS` beside it, consulted only after the fail-closed
> gate. `tests/test_client_handled_commands_contract.py::
> TestVscodeRosterDrivenDispatchOrder` pins it at exactly
> `{tools, checkpoint, context, ls, tree}`, pins that no command with a
> declared `client_action` appears in it, and pins that no legacy name
> leaked into `CLIENT_ACTIONS`. Step 5 inherits that list rather than
> re-deriving it; it may only shrink, and only by migrating a command to
> factory routing.

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

## The guard, and what replaced it (step 4, 2026-09-21)

`tests/test_no_new_lazy_imports.py::TestEngineCompletionStaysALeaf`
(2026-09-20) fenced the SYMPTOM: `engine.completion`'s leaf status, which
was the only thing keeping the `engine → commands → engine` package cycle
dormant. It proved the cycle rather than inferring it — a module-scope
import of `engine.completion` from `engine/client.py` killed the pytest
run at collection with a partially-initialized-module `ImportError`.

Step 4 removed the upward import, so the guard was **deleted** (as its own
failure message instructed) and replaced by the rule itself:
`TestEngineImportsNoCommands` — no module under `ppxai/engine/` imports
`ppxai.commands`, at module scope or inside a function, held at ZERO,
guards-first, same style as `TestConfigDoesNotImportEngine`.

Re-mutating on the new shape gave a different answer worth keeping: with
the deleted import restored at module scope **nothing fails but the
fence** (6,285 tests still collect, `import ppxai.engine.completion` still
succeeds standalone, the completion suites stay green). The edge is
invisible in production; the test is the only thing that sees it.
