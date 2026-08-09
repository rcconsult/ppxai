# Shared lessons

Cross-host engineering hazards and verified architectural facts that
any agent (AI or human) working on this codebase should know **before**
they start re-deriving them.

This directory exists because per-host AI memory
(`~/.claude/projects/<repo>/memory/` on each developer's machine) does
NOT sync. A lesson written on macOS isn't visible to a session on
Windows. Authoritative cross-host knowledge belongs in the repo, where
`git pull` is the sync mechanism.

## What belongs here

A lesson belongs in `docs/lessons/` when it meets **both** criteria:

1. **Cross-host relevance.** The lesson is true on any machine running
   this repo — not specific to one host's path quirks, shell, or
   installed-tool versions.

2. **Verifiable from code.** A reader can `grep`, open a file, or run
   a one-line check to confirm it. The lesson is grounded in
   observable repo state, not in "Claude on Windows once hit X."

Examples of cross-host + grep-verifiable lessons:

- "ppxai imports `mcp` nowhere — the `[mcp]` optional extra is intent,
  not implementation" (verifiable: `Grep "import mcp" ppxai/`)
- "`tool_manager.py:193` hardcodes `source: engine`, blocking
  extension by external tool sources" (verifiable: open the file)
- "ADR 0006 producer-side keys MUST stay off the wire — the
  `__debug__`-gated `assert_wire_blocks_clean` validator enforces it"
  (verifiable: read `engine/uploaded_file.py`)

## What does NOT belong here

Stays in per-host memory (`~/.claude/projects/<repo>/memory/`):

- **User-preference notes** — "this user prefers terse responses",
  "don't expand scope without permission"
- **Host-specific paths** — Windows `code.cmd` shim, macOS `hdiutil`
  invocations, rtk hook is bash-only on Windows
- **Session scratchpads** — "branch X in flight, commit Y next",
  "just verified Z this turn"
- **Agent self-discipline reminders** — "verify both directions",
  "read files don't infer"

These stay private because they're either personal preference or
ephemeral context. Promoting them here would mix signal (engineering
hazards) with noise (per-developer prefs) and hurt both.

## Format

Each lesson is a short markdown file with this shape:

```markdown
# <Short title — the lesson, not the symptom>

**TL;DR:** One sentence stating the fact.

**Verify with:** `<grep command | file path | one-line check>`

## Why this trips people up

What looks like evidence-of-X that actually isn't, or the surprising
behavior that doesn't match the obvious mental model. The trap.

## What's actually true

The fact, grounded in repo state. Include file path + line numbers
where they help the reader confirm.

## Related

Links to ADRs, ROADMAP entries, or other lessons.
```

Keep each lesson under 100 lines. If the topic needs more space,
it's probably an ADR or design doc, not a lesson.

## Promotion workflow (for AI agents)

When you discover a hazard during a session:

1. **Triage:** does it meet both criteria above (cross-host +
   grep-verifiable)?
2. **If yes:** propose adding a `docs/lessons/<topic>.md` file in
   the user-facing summary of your turn. Don't auto-commit;
   the user decides whether the lesson is worth the repo's
   permanent attention.
3. **If no:** save to your per-host memory only.

Same gesture as filing an ADR — deliberate, human-in-the-loop,
discoverable later.

## Index

- [mcp-not-yet-integrated.md](mcp-not-yet-integrated.md) — ppxai
  has filename-level MCP breadcrumbs but zero integration; v1.20.x
  plan at `docs/MCP-INTEGRATION-PLAN.md`
- [config-source-resolution.md](config-source-resolution.md) —
  `PPXAI_CONFIG_FILE` (often set via repo-root `.env`) overrides
  `./ppxai-config.json`; editing the obvious project config can
  silently have no effect on the server
- [loopback-ui-auth-exemption.md](loopback-ui-auth-exemption.md) —
  with auth on, loopback `/chat` + `/files/read` are bearer-EXEMPT by
  source-IP alone (any local process, not just the operator's browser);
  deliberate desktop-UX choice, not a bug — don't drive-by "fix" it
- [testclient-per-request-event-loop.md](testclient-per-request-event-loop.md) —
  non-context `TestClient(app)` gives every request its own event loop;
  a background task that must live ACROSS requests (T5 consent park)
  silently dies — use `with TestClient(app) as c:` (`ctx_client` fixture)
- [stale-server-invalidates-acceptance.md](stale-server-invalidates-acceptance.md) —
  ppxai-server binds a FIXED port (54320); a stale server makes a freshly
  spawned binary die silently, so acceptance tests the OLD process — free
  the port first (`gateway-smoke.py` now guards this)
- [perplexity-alternation-retired-orphan-toolcalls-is-real.md](perplexity-alternation-retired-orphan-toolcalls-is-real.md) —
  Perplexity Sonar relaxed the old "messages must alternate" rule (verified
  live); the recurring tools-chat 400 is the provider-agnostic orphan
  `assistant.tool_calls` case — check the actual wire error before adding
  another alternation patch
- [stale-tests-outlive-deleted-behavior.md](stale-tests-outlive-deleted-behavior.md) —
  removing a behavior leaves its tests behind; they fail as assumed-
  environmental noise or keep passing against a renamed surface while
  guarding nothing. Invert, retarget, or delete — and mutation-test the fence
- [qwen-27b-vl-empirically-supported.md](qwen-27b-vl-empirically-supported.md) —
  Qwen3.5/3.6-27B-FP8 empirically accept `image_url` content via vLLM;
  ppxai's `model_profiles.py` lacked `supports_vision=True` entries for them
  (fixed 2026-06-08, `model_profiles.py:481-505`)
- [web-assets-served-from-ppxai-home.md](web-assets-served-from-ppxai-home.md) —
  clients serve the web UI from `~/.ppxai/web`, not the repo source tree;
  editing `web/` in-repo has no effect on a running server without
  `PPXAI_WEB_DIR` pointed at the checkout
- [clean-break-config-moves-need-a-file-scan.md](clean-break-config-moves-need-a-file-scan.md) —
  a config key moved with NO dual-read is invisible to every accessor, so a
  stale key silently reverts to its default; only a check that reads the
  config FILE can detect it (`/doctor`'s ADR 0010 section) — ship that scan
  with the move, not as cleanup

- [parity-harness-must-know-every-client.md](parity-harness-must-know-every-client.md)
  — a multi-client parity harness that knows N-1 clients is a blind spot. Adding
  a client is a change to the harness FIRST. Cost: three shipped-missing
  capabilities that no test caught (2026-08-09).
- [module-level-home-paths-leak-into-user-state.md](module-level-home-paths-leak-into-user-state.md)
  — `Path.home()` constants resolve at IMPORT time, so isolating a directory
  through a constructor does not stop a test writing the user's real state.
  Cost: the suite silently clobbered the developer's session pointer.
