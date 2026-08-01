# Debt Inventory — Closed-Item Archive (rolling)

Full bodies of closed debt items, moved here from
[docs/debt-inventory.md](../debt-inventory.md) to keep the rolling inventory
scannable. **Item numbers are never reused or renumbered** — the sequence is
global across the inventory and this archive. Per-version snapshots
(v1.18.2/v1.18.3 pattern) remain in their own files; this file is the rolling
archive for the branch-by-branch closes since then.

---

## Closed on `feature/v1.19.0` / `bugfix/v1.19.1` (archived 2026-08-01)

### Item 24 — Non-vision image attach silently degraded to a hallucination-feeding placeholder  ✅ RESOLVED (v1.19.0)

> **Resolution (2026-06-23, `feature/v1.19.0`):** both halves landed.
>
> **(1) Detection — already fixed earlier this cycle.**
> `model_profiles.py` now carries `supports_vision=True` globs for
> `Qwen/Qwen3.[56]-27B-FP8*` (and `Qwen3.6-35B-A3B-FP8*`); this session
> also pinned the `-agent` suffix variant the codeai cluster serves
> (`Qwen/Qwen3.6-27B-FP8-agent`) in `test_model_profiles.py`. The
> originally-reported diagram now routes as a real `image_url` block.
>
> **(2) Fail-loud + tool route — this session.** The secondary "fallback
> wired but doesn't run" class is closed by removing the silent
> placeholder entirely. `_preprocess_image` (`file_preprocessing.py`) now
> routes an image by a 4-way gate:
>   1. native vision (`supports_vision`) → `image_url` block;
>   2. VL sidecar caption (`vl_captioner`) → text caption;
>   3. **NEW** shell-CLI route — when the session has the shell tool
>      enabled (`EngineClient.can_shell_process_images()` →
>      `multimodal_ops.session_can_shell_process_images`), surface the
>      persisted on-disk path so the model can OCR/convert via a system
>      utility (ImageMagick/tesseract). No upfront utility probe — if none
>      is installed the model's shell call fails with a real, reportable
>      error (user decision: "permit + surface the path");
>   4. **else → `ok=False` fail-loud** with an actionable error (switch to
>      a vision model / restart with a reachable sidecar / enable the shell
>      tool). The bytes are still persisted and the `file_id` is surfaced on
>      the failure result so a retry can reach the same asset.
>
> Consumers: the server chat route (`server/routes/chat.py`) blocks the
> send on `ok=False` and emits a structured `vision_unsupported`
> (severity **error**) warning; on indirect success it emits
> `vision_via_tool` (shell route) or `vision_via_caption` (sidecar),
> distinguished by the route marker in `PreprocessResult.warnings` so the
> user notice matches the route actually taken. `commands/attach.py`
> (Rich/Textual `/attach`) surfaces the failure inline as
> `[Attachment error: …]` and never emits an `image_url`. Stale
> "sent as a text placeholder" copy removed from `web/app.js` (attach-time
> notice) and the VSCode `stream.ts` comment. All four call sites
> (`chat.py`, `attach.py`, `tui/app.py`, `rich/main.py`) compute and thread
> `shell_image_route`.
>
> **Tests:** `test_file_preprocessing.py` (`TestImageTextOnlyFailLoud`,
> `TestImageShellRoute`, captioner-empty → fail-loud / shell-route),
> `test_vision_sidecar.py` (`TestCanShellProcessImages`,
> fail-loud + shell-route when sidecar unavailable),
> `test_attach_vision_warning.py` (severity escalated warning→error).
> 319 passing across the vision/attach/multimodal suites; VSCode `tsc`
> clean.
>
> **Not addressed (intentional):** the dead `tools.vision_model.auto_caption`
> config flag (read but never consulted) — superseded by the explicit
> `vl_captioner`-wired-when-`has_vision_sidecar()` path; filed separately if
> it ever needs removal. The original root-cause diagnosis (why the sidecar
> didn't fire on coder.internal) is moot now that there is no silent
> placeholder to fall into.

---

---

### Item 24 (historical) — VL sidecar `auto_caption` fallback silently no-ops on non-vision models

**Affected files:** `ppxai/engine/multimodal_ops.py` (`auto_caption_image` and the
`get_vision_model_config()` consumers around L575–640), `ppxai/engine/file_preprocessing.py`
(L235–290, the `supports_vision(model)` routing branch), the chat-attachment path that
delivers the "It was sent as a text placeholder" warning to the web UI.

**What's wrong:** when the active model is text-only AND `tools.vision_model.auto_caption: true`
is configured with an enabled, reachable VL sidecar (the documented "Qwen3-VL caption
gateway" pattern used by the coder cluster — `Qwen/Qwen3-VL-8B-Instruct` at
`vllm-qwen3-vl-8b-fp8-lmcache-mig.vllm.svc`), the image-attach pipeline is
**expected** to call the sidecar, get a caption back, and inline it into the user
message so the text-only model receives describable content. Dogfooded on
coder.internal 2026-06-08 with the Qwen/Qwen3.5-27B-FP8 vllm-qwen35 provider: an
attached `.drawio.png` network diagram surfaced the `vision_unsupported` warning
("sent as a text placeholder") and the model then **hallucinated a fully
fabricated description of "empty 35mm film reels"** — the worst of both worlds.
Detection was correct (`supports_vision('Qwen/Qwen3.5-27B-FP8') = False`,
conservative default — no Qwen3.5-base profile entry); the auto-caption fallback
just never fired. Why is unconfirmed — candidates: sidecar unreachable from this
namespace, 30s timeout silently swallowed, the drag-drop UI path taking a
branch that bypasses `multimodal_ops.auto_caption_image`, or `enabled: true`
but the actual call erroring with no surfaced message.

**Why deferred:** detection logic is correct and the warning fires; the user
sees "sent as a text placeholder", so the failure isn't silent at the UI layer.
The downstream model hallucination is a model-quality issue, not a ppxai bug.
Workaround: switch to a true VL provider (gemini-2.5-flash, gpt-5.5, dgx-cluster
once the model swap lands), or check the VL sidecar health from the pod and
attach again. The class of bug — "fallback that's wired but doesn't run" —
deserves a sentinel; not a release blocker.

**Planned:** `bugfix/v1.18.8` or whichever v1.18.x branch follows. Trigger an
investigation pass that probes the actual auto_caption code path end-to-end on
the coder cluster (image attach → does the sidecar receive the POST?), surfaces
the failure mode in the user warning (currently "sent as a text placeholder" is
indistinguishable from "tried sidecar and it failed"), and adds an integration
test that mocks a text-only active model + a reachable VL sidecar and asserts
the caption is inlined into the message rather than the placeholder.

**Branch when ready:** `bugfix/v1.18.8` (open-items follow-up) or
`fix/vl-sidecar-fallback` (focused).

**Trigger to revisit:** any second report of "I attached an image and the
model made up a description" on the coder cluster, OR before the dgx-cluster
model swap to confirm we're not stacking another fallback gap, OR if anyone
adds a new modality (audio/video) — same pattern likely lurks for those too.

**Effort:**
- Diagnose root cause (~1 hour): tail pod debug log on next image attach;
  grep for `vision_model` / `caption` / `Qwen3-VL`; in-pod `curl` to the
  sidecar to confirm reachability; check `multimodal_ops.auto_caption_image`
  for swallowed exceptions.
- Fix + surface (~half day): if cause is timeout or unreachability, distinguish
  the warning text ("VL sidecar timed out (30s) — re-attach to retry" vs
  "sent as text placeholder, active model is not vision-capable"); if cause
  is a code-path bypass, route the drag-drop path through the same handler
  as `/attach`.
- Integration test (~1 hour): mock active=text-only model + mock vision_model
  endpoint; assert caption inlined into user message.

**Surfaced by:** coder.internal dogfooding 2026-06-08, drawio.png attach to
the vllm-qwen35 provider.

> **Update 2026-06-08 (same day):** the user pushed back that they're sure
> they tested these 27B models and they support VL. Cross-repo search found
> two artifacts that prove the user was right and reframe this item:
>
> 1. `/path/to/trad-ai-chat/scripts/test-vl-capabilities.sh`
>    (commit `916772c`, 2026-04-23) — 9-test VL probe (Test 0 image accept,
>    Test 1 OCR, Test 2 tables, Test 3 charts). Baseline run against
>    `https://codeai.internal/qwen35/v1` model `Qwen/Qwen3.5-27B-FP8`
>    scored **8/9 PASS**. The one fail (Test 2b) was arithmetic-over-OCR'd-data
>    reasoning — NOT vision.
> 2. `/path/to/trad-ai-chat/doc/research/qwen35-vs-qwen36-27b-comparison.md`
>    (2026-04-30) — confirms Qwen3.6-27B-FP8 has an **explicit vision
>    encoder** added in the architecture ("Text + image + video"); Qwen3.5
>    is labeled "Text-only" on the HF card but empirically handles
>    `image_url` content through vLLM. Comparison doc recommends the
>    `test-vl-capabilities.sh` script as Gate A for the Qwen3-VL
>    decommission (CR-v4.0.0 Part 2 Phase 6).
>
> **Reframed root cause:** ppxai's `model_profiles.py` has no entry for
> `Qwen/Qwen3.5-27B-FP8` or `Qwen/Qwen3.6-27B-FP8` (`supports_vision()`
> falls through to default `False`). The HF card "Text-only" label on 3.5
> is wrong for the model's behavior through vLLM, and 3.6's vision encoder
> is real. **The detection is wrong; the model would have shown the diagram
> correctly if ppxai had sent the `image_url` block.**
>
> **Revised fix path (priority bump — Item 24 jumps above 21–23):**
>
> 1. Add `model_profiles.py` entries with `supports_vision=True` for both
>    `Qwen/Qwen3.5-27B-FP8` and `Qwen/Qwen3.6-27B-FP8` (or a glob
>    `Qwen/Qwen3.[56]-27B-FP8`). Sentinel test in
>    `test_model_profiles.py`. **5-minute change.**
> 2. Re-run `test-vl-capabilities.sh` against the coder cluster's actual
>    endpoints to confirm both models still pass 8/9+; capture the run as a
>    memory snapshot. **30 min.**
> 3. The original sidecar-fallback diagnose (the "fallback wired but
>    doesn't run" class) is now SECONDARY but still real — it would fire
>    for genuinely text-only providers (e.g. `openai/gpt-5-nano`). Keep
>    the half-day estimate for that part as a separate concern.
>
> See [[reference-qwen-27b-vl-empirical]] (memory) +
> `docs/lessons/qwen-27b-vl-empirically-supported.md` (in-repo lesson, this
> commit) for the cross-host evidence trail so the next session doesn't
> have to re-derive.

---

---

### Item 40 — web + VSCode clients cannot present a bearer token; `/task` unusable on auth-enforcing hosts [agent platform / clients] — ✅ FIXED (2026-07-11; web live-trialed 2026-07-12 under an enforcing file store: bearer-less `/task ls` → 401, `/token mint` → stored, `/task ls`/`show` work incl. status-aware run-id completion. VSCode "Set API Token" path unit-covered, not yet live-trialed)

**Build (landed):** both clients grew a /v1-scoped bearer seam — scoped to
`/v1/*` ONLY because `server/auth.py` validates any presented bearer even on
loopback-exempt UI routes (a stale token attached everywhere would 401 the
whole client, not just the agent API).

- **web:** `ApiClient.setApiToken()` + `headersFor(endpoint)` (get/post +
  the `_tailEvents` live stream); token persisted in
  `localStorage['ppxai-api-token']`, restored on app init. New client-side
  **`/token status|set|mint|clear`** command (command-dispatcher):
  `set` takes the value via `window.prompt()` — NEVER inline, every
  dispatched command line is echoed into the server debug log; `mint`
  self-provisions via the loopback bootstrap (`POST /v1/tokens`, sent
  bare — a stale stored bearer would be validated and rejected even on
  the exempt mint). `/token` registered in both web catalogs + the
  engine completion builtins (`_TOKEN_SUBCOMMANDS`).
- **VSCode:** `HttpClient.setApiToken()` + `v1Headers()` used by all 8
  agent-slice call sites (task/runs/run/events/cancel/respond/ack/resume);
  token in `SecretStorage` (`ppxai.apiToken`) — never settings.json (sync +
  dotfile leak) — via the new `ppxai.setApiToken` command (masked input;
  empty submit clears).
- **Follow-up (2026-07-12, from the VSCode trial leg):** the palette-only
  VSCode flow was undiscoverable — server-driven autocomplete offered
  `/token` (engine builtin), dispatch answered "Unknown command", and the
  `/task` 401 never named the fix. Landed: (1) the same in-chat
  **`/token status|set|mint|clear`** family in VSCode (`chatPanel.ts`,
  same SecretStorage key as the palette entry; bare `set` opens the
  palette's masked input; `mint` self-provisions via
  `HttpClient.mintApiToken('vscode-local')`, sent bare like web);
  (2) per-client completion gating — `complete(..., client=)` +
  `_CLIENT_GATES` in `engine/completion.py` hide client-side commands
  (`/task`, `/token`, `/agentrun`, `/agentruns`) from clients that don't
  implement them (TUIs now see none of them; fail-open for legacy
  callers); (3) a 401 from any `/task`/`/agentrun` verb now appends
  "run `/token mint` … or `/token set`" in BOTH clients
  (`taskController.errText` / `agent-run-controller._errText`).
  Fences: `TestTokenCommandParity` + `TestClientGating`.
- **Tests:** `tests/test_api_client_auth_behavior.py` (Node harness — bearer
  on /v1 GET+POST, absent on UI routes, headersFor seam, clear);
  `tests/test_vscode_task_controller.py::TestBearerParity` (6 sentinels —
  both seams exist, every VSCode agent call site uses `v1Headers`, secret
  sources are the safe ones). Server side unchanged — already covered by
  `test_auth_middleware.py` + `test_tokens_v1_route.py`.

**Trial recipe:** restore the file token store
(`cp ~/.ppxai/ppxai-config.json.backup.tasktrials ~/.ppxai/ppxai-config.json`),
restart the server, web UI: `/task ls` → expect 401 error; `/token mint` →
minted+stored; `/task ls` again → works; `/task run …` full T5 flow under
auth. VSCode: `/task ls` → expect 401 **with the `/token` hint** →
`/token mint` → `/task ls` works (or: palette "ppxai: Set API Token" /
`/token set` to paste one — both write the same SecretStorage key).

**Original entry (for context):** neither shipped client can authenticate to the v1 agent
API. `ppxai/web/` has zero `Authorization` handling and so does
`vscode-extension/src/` (verified by grep 2026-07-11). Meanwhile
`/v1/agent/*` stays bearer-protected **even from loopback** (Inc 8b:
`_LOOPBACK_PROTECTED_PREFIXES` in `server/auth.py`; only the tool-free
`/v1/agent/run` + unowned-run reads are carved out), and auth is enforced
whenever a mint-capable store is configured (`server.secrets.providers`
containing `file` — presence ⇒ enforce, even with zero tokens). Net effect:
on any host with a file token store, the ENTIRE `/task` family 401s from
both shipped UIs. Caught live in the 2026-07-11 T5 trial on this host
(file store left over from the Inc 8 `/v1/tokens` trial); worked around by
temporarily removing the file provider from the user config.

**Why it wasn't caught earlier:** every T1–T8a live trial ran on auth-off
hosts (no mint-capable store configured), which is the fresh-install
default — the trial recipes never mention tokens because they never needed
one.

**What's needed:** per-client token plumbing, not a server change:
- **web:** a settings affordance to store a token (localStorage) +
  `Authorization: Bearer` injection in `apiClient` and the SSE/event-tail
  fetches; the loopback-exempt `POST /v1/tokens` bootstrap mint (Inc 8a)
  already gives a local browser a way to acquire one.
- **VSCode:** `ppxai.apiToken` via `SecretStorage` (not settings.json) +
  the same header in `httpClient.ts` (incl. `agentRunEvents`).
- Parity sentinels: extend `tests/test_vscode_task_controller.py` so the
  header wiring can't drift between the two clients.

**Release consideration:** v1.19.0 ships `/task` in web + VSCode as a
headline feature — "unusable the moment an operator configures the token
store" is a real deployment cliff. Either land this before tagging or
document the auth-off requirement loudly in the release notes.

**Effort:** ~half a day both clients + sentinels.

---

---

### Item 41 — Gemini provider tool-loop fidelity: no `tool_call_id` threading; `_filter_empty_parts` is dead code [providers / gemini] — ✅ RESOLVED (2026-07-12, same-day)

Found while diagnosing the deny-path empty-result bug (T5/T7 trials; the
symptom fixes landed with §M — see
[agent-platform-call-graphs.md](agent-platform-call-graphs.md)). Two
structural gaps, both verified by source read + grep, both fixed same day:

1. **`_convert_messages` (gemini.py) never threaded `Message.tool_calls` /
   `tool_call_id`** (unlike `openai_native.py`), and `_parse_function_call`
   never emitted a `tool_call_id` — so `engine/chat.py`'s native
   tool-result pairing branch was **dead for Gemini**: every tool
   round-trip flattened through the synthetic assistant/user text path,
   an off-label transcript shape that plausibly drove the model quirks
   observed live (the `default_api:` prefix echo, atypical continuations
   after a denial). **Fixed:** `_parse_function_call` threads the SDK's
   `FunctionCall.id`, synthesizing `gemini-fc-<uuid12>` when absent (the
   engine's pairing branch requires an id per call; the id never goes
   back on the Gemini wire), both TOOL_CALL emission sites carry it, and
   `_convert_messages` maps the engine's native transcript shape onto
   Gemini's wire format — assistant `tool_calls` → model `function_call`
   parts, tool-role messages → user `function_response` parts paired by
   function NAME via an id→name map built from the preceding model turn
   (Gemini pairs responses by name, not id). Unpaired tool results
   degrade to plain user text turns.
2. **`_filter_empty_parts` had zero call sites** (the v1.15.3 call sites
   were lost in a later refactor). **Deleted** — the response parse loops
   already skip empty text parts inherently, and SDK 2.11.0 passed the
   KI-001 gate with no filter in the path. A sentinel test pins the
   deletion.

**Verification (2026-07-12):** `tests/test_gemini_native_tool_loop.py`
(18 tests: id threading, TOOL_CALL event shape in both response modes,
native transcript conversion incl. parallel calls / unpaired results /
malformed args, deletion sentinel); full suite 4560 passed / 0 failed;
benchmark gate 3× gemini-2.5-flash on SDK 2.11.0: overall
80.7 / 72.6 / 73.8%, code editing 100/100/100 — at or above the
pre-change 2.11.0 baseline (74.4/70.2/74.4), so the native transcript
shape is benchmark-neutral-to-positive. **Live-trial follow-up:** watch
whether the `default_api:` prefix echo and post-denial continuation
quirks disappear in the next `/task` Gemini trials.

---

---

### Item 42 — orphan `assistant.tool_calls` ate user prompts + reached strict providers [session / chat] — ✅ FIXED (2026-07-13, `bugfix/v1.19.1` `46599e8f`)

Surfaced by a live VSCode tools-enabled trial (2026-07-12; logs
`~/.ppxai/logs/chat-debug.log` 21:58–22:01 + `session-debug.log`). Two
defects, both reproduced deterministically before fixing:

1. **Data loss.** `SessionManager.validate_and_fix_alternation` stripping a
   tail orphan `assistant.tool_calls` (its `tool` replies missing — a
   cancelled/interrupted tool) exposed a trailing user, which the
   trailing-user drop then deleted as an "unsent draft" — the recurring
   `DROPPED UNSENT USER PROMPT … 'What is the capital of France?'` (len=30)
   log line was eating **real** prompts (the model had begun answering via
   the removed `tool_calls`). **Fixed:** `orphan_exposed_trailing_user`
   guard keeps it; a genuine mid-turn draft is still dropped.
2. **Orphan on the wire mid-turn.** The pre-flight runs once before the
   `chat_with_tools` loop; iterations 2+ (and the empty-after-tools retry)
   sent `get_messages()` raw, so a mid-turn orphan reached a strict provider
   and 400'd (`"… tool_call_ids did not have response"`, observed live on
   OpenAI `gpt-5.4-mini`). **Fixed:** orphan-strip extracted to module-level
   pure `strip_orphan_tool_calls()`; applied to the **outbound** copy before
   each in-loop send (session state untouched).

**Verification:** `tests/test_orphan_toolcalls_regression.py` (5). Regression
sweep clean (307 across R15/agent-runs/session-schema/gemini-native-tool-loop;
180 across session/streaming/tool/multimodal). Lesson:
`docs/lessons/perplexity-alternation-retired-orphan-toolcalls-is-real.md`.

---

### Item 44 — interactive empty-response retry persists an empty-content assistant → Perplexity 400 [chat / providers] — ✅ FIXED (2026-07-13, `bugfix/v1.19.1`)

`chat_simple` and `chat_with_tools` add a synthetic `Message("user", "Please
proceed…")` on an empty response and retry. When retries exhausted, the loops
fell through to `add_message(Message("assistant", full_response))` with
`full_response == ""`, persisting an **empty-content** assistant AND leaving
the synthetic nudge in history. On the next turn the empty assistant was
resent; current Perplexity Sonar rejects it with
`{'message':'Message content was empty','type':'invalid_message'}` (verified
live 2026-07-13). Distinct from Item 42's orphan case. Root cause: nudge
retries were treated as valid conversation turns instead of transient repair.

**Fixed structurally (Option D — producer root-fix + outbound guard, mirroring
Item 42's two-role pattern):**

1. **Producer.** `finalize_empty_response()` (module-level in `engine/chat.py`)
   rolls back the transient `EMPTY_RESPONSE_NUDGE` user turn (via
   `remove_last_message`, guarded on exact text) and coalesces empty content to
   the `EMPTY_RESPONSE_SENTINEL` (`"[No response generated]"`). Applied on every
   empty-exhaustion path in both loops, unifying them with the already-correct
   `chat_with_tools` iteration>1 path (which rolled back its own prompt +
   coalesced to `"[Tool execution completed…]"`). The nudge text is now a single
   `EMPTY_RESPONSE_NUDGE` constant, not open-coded in three places.
2. **Repair-on-load.** Pure `strip_empty_assistant()` in `engine/session.py`
   (drops assistant turns with no `tool_calls` and no text; preserves native
   tool-calling turns), wired into `validate_and_fix_alternation` right after
   the orphan pass — heals sessions saved by ppxai ≤ 1.19.0 that already carry
   an empty turn. The Bug-A `orphan_exposed_trailing_user` guard was widened to
   also cover an empty-strip that exposes a genuinely-answered trailing user.
3. **Outbound guard.** New composed `sanitize_outbound()` chains
   `strip_orphan_tool_calls` + `strip_empty_assistant` into one call, replacing
   the two raw orphan-strip sites in the tool loop — so both malformations are
   cleaned from the wire copy at a single entry point (session state untouched).

**Verification:** `tests/test_orphan_toolcalls_regression.py` (+8 → 13 total):
pure strips + composition, self-heal on load, empty-strip-exposed trailing-user
preservation, producer nudge-rollback + sentinel + narrow-guard. Session
persistence/restore/migration sweep clean (121 pass / 6 Windows-symlink skips);
chat-loop suites clean (74).

---

---

### Item 45 — Gemini 3.x native tool round-trip 400s: `thought_signature` never preserved/replayed [providers / gemini / agent platform] — ✅ FIXED (2026-07-22, `bugfix/v1.19.1` `edb74500`)

**Fixed:** the signature is threaded along the full path it must survive —
response part → `_parse_function_call(fc, part)` → `TOOL_CALL` event →
session `tool_calls` entry (`chat.py`) → outbound `functionCall` part
(`_convert_messages`). `_thought_signature_of()` reads the PART (documented
location), probes the FunctionCall defensively, and base64-encodes bytes so
the value survives the JSON round-trip through the session store. Gemini 2.5
never sends the field → key absent → that path byte-identical to before.
Tests: `tests/test_gemini_thought_signature.py` (11).
**Third reproduction before the fix (2026-07-22, desktop web):** same 400 on
`web_search` rather than `read_file`, confirming the bug was **tool-agnostic**
— it broke *every* native tool round-trip on 3.x.

**Planned:** `v1.19.x` — **higher priority than Item 43: this breaks the
*working* native-tool path.** Surfaced in the 2026-07-13 web-app trial. A
`/task` "summarize docs/README.md" (`--tools read_file`) on
`gemini-3.1-pro-preview` correctly enters native mode and emits a **real**
`read_file` call (`events.jsonl` `tool_call read_file`; validator
`Recorded tool call: read_file success=True`), then the follow-up turn 400s:

```
Gemini error (ClientError): 400 INVALID_ARGUMENT — Function call is missing a
thought_signature in functionCall parts. … function call `default_api:read_file`,
position 2. https://ai.google.dev/gemini-api/docs/thought-signatures
```

Reproduced twice: `run_b06fa96cf44f`, `run_1650174cfe2d`. **Root cause
(source-verified):** `thought_signature` / `thoughtSignature` appears
**nowhere** in the codebase (`grep -ri thought_signature ppxai/` → empty).
Gemini 3.x requires each returned `functionCall` part to carry an opaque
`thought_signature` that the client must **echo back** on the tool-response
turn; our Gemini provider drops it. Blocks **all** native-tool `/task` runs
on Gemini 3.x models.

**Relationship to Item 41 (RESOLVED 2026-07-12).** Item 41 fixed
`tool_call_id` threading + native transcript conversion for the SDK's
`FunctionCall.id`. It did **not** touch `thought_signature` (a distinct
Gemini-3.x field) — that path was never exercised on a 3.x model in the
Item 41 trials, so this is new, not a regression of that fix.

**Fix direction (not yet built):** in the Gemini provider, capture
`part.thought_signature` from each returned `function_call` part into the
engine's tool-call record, and re-attach it on the corresponding
`function_response` part in `_convert_messages`. Mirrors the id→name pairing
Item 41 added, but for the signature blob. `tests/test_gemini_native_tool_loop.py`
is the natural home for the sentinel.

---

### Item 50 — `/task` accepted a grant naming a nonexistent tool [agent platform / validation] — ✅ FIXED (2026-07-22, `bugfix/v1.19.1` `edb74500`)

Observed live 2026-07-22 (desktop web): `/task run … --tools "weather,
web_search"` was **accepted and started** although the tool is `get_weather`.
The `ScopedToolManager` is only built inside the runner, so an unknown name
sailed through run creation, the model was silently offered fewer tools than
the caller believed it granted, and the run burned an LLM call before failing
for a reason invisible to the caller.

**Fixed** with `ScopedToolManager.unresolved_grant()` /
`unresolved_grant_message()` — that object already holds **both** halves of
the question (the grant, and the base manager with every tool registered for
the run), so no parallel registry is introduced. The message suggests the
near-miss (`'weather' (did you mean 'get_weather'?)`) via difflib plus a
substring fallback difflib's ratio misses on short needles.

**Placement is load-bearing, not incidental.** editor/shell/container/display
tools register **only when an engine is present**, so a registry rebuilt
without one reports a misleading subset — a first attempt at route-level
validation saw **9 of 44** tools and **falsely rejected `apply_patch`**. The
check also degrades to a no-op when the base manager cannot enumerate tools
(minimal/duck-typed managers in tests and embedders): grant *hygiene* must
never be the reason a run fails to start; AC-1 *enforcement* is untouched.
Tests: `tests/test_scoped_grant_validation.py` (9).

---

### Item 51 — Gemini `oneshot()` returned the model's reasoning as the answer [providers / gemini] — ✅ FIXED (2026-07-22, `bugfix/v1.19.1` `edb74500`)

Observed live 2026-07-22: an `/agentrun` weather query on
`gemini-3.1-pro-preview` returned *"**My Thought Process: Weather Inquiry for
Castelfranco Veneto** — Okay, the user wants weather information… I'll need to
clean up that typo…"* as the **result**.

Root cause: `chat()` has always split thinking parts out (`part.thought` →
`REASONING_CHUNK`, kept out of `full_response`), but `oneshot()` concatenated
**every** text part with no `thought` check — and `/agentrun` drives `oneshot`.
**Fixed** by applying the same thought/answer rule in `oneshot()`, exposing the
monologue additively as `result["reasoning"]` (callers reading only `content`
are unaffected), and falling back to the reasoning text only when the model
produced nothing else — so a thought-only response never looks like an empty
completion. Tests: `tests/test_gemini_thought_signature.py::TestOneshotThoughtSplit` (4).

---

## Former "Closed (recent)" section (verbatim, archived 2026-08-01)


For full closed-item rationale with commit references, see the per-version
archived snapshots:

- **Item 24 — non-vision image attach fail-loud + shell-CLI route (closed 2026-06-23, `feature/v1.19.0`):**
  removed the silent "text placeholder" that fed model hallucination on
  text-only models. Detection fixed earlier this cycle (`Qwen3.[56]-27B-FP8*`
  vision globs + `-agent` variant pinned); this session added the shell-CLI
  consumption route (`can_shell_process_images()` → on-disk path surfaced for
  OCR/convert) and made the no-path case fail loud (`ok=False`, send blocked,
  actionable error). Structured warnings disambiguate route taken
  (`vision_via_tool` / `vision_via_caption` / `vision_unsupported`@error).
  319 vision/attach/multimodal tests green; VSCode `tsc` clean. Full
  resolution detail still inline under the RESOLVED Item 24 entry above
  (kept with its evidence trail until the next archive sweep).

- **Post-files-parity v1.18.8 review fixes (closed 2026-06-14):** beyond the
  `/files/*` items (25–28, 30–32), two parallel reviews + live desktop testing
  surfaced and closed: **cross-platform LibreOffice discovery** (`9d1c7550` —
  macOS `soffice`/`.app` was undetected, raster preview dead by default; +
  formatted install card) and its CI-safe test fix (`4b60970f`); **three
  session save/load security findings** (`de3b56d7` — path traversal in
  names, stale attachment file_ids on load, corrupt-load file-store
  corruption); and the **session auto-restore-mode** bug (`1fe60ea5` — web
  client ignored `auto_restore` and used a fragile `confirm()`, so restore
  landed on fresh defaults; `/status` now exposes the mode). All with
  regression tests. See [CHANGELOG.md](../CHANGELOG.md) `[1.18.8]`.

- **Item 28 — OfficeFileView blob-revoke race + attachment text_fallback (closed 2026-06-14):**
  `ef17f748` on `bugfix/v1.18.8`. The attachment renderers (`app.js`) gained an
  `unmounted` flag so the async `.then()` no longer creates a leaked blob URL
  into a detached container; the text-fallback sites now assert a string
  `content` (surface `missing "content" key` instead of `'(empty)'`). Also
  followed through on item 26: the attachment path now branches on
  `libreoffice_available`/content-type and degrades to extracted text (via a
  new shared `OfficeFileView.renderTextFallbackInto()`), so chat-bubble
  attachments degrade like the file tree instead of rendering JSON as a slide
  image / PDF. Web-only; `node --check` clean, DOM = manual-smoke. v1.18.8
  Phase F (3/3). **Follow-up (`84ee33c2`, post-review):** (a) closed a residual
  `renderSlideNavInto` leak — it created the object URL *after* `await
  fetchSlideBlob`, so an unmount mid-fetch leaked the post-await URL; added a
  `disposed` flag (fixes attachment **and** file-tree PPT previews). (b) Fixed
  the **VSCode** twin of the web JSON-as-binary bug: `chatPanel.ts` wrote every
  ok `/files/preview` response to `.png`/`.pdf`, so the item-26 200 JSON
  text_fallback became a garbage image/PDF — now branches on
  `libreoffice_available`/`type` + content-type and falls back to the raw file.

- **Item 26 — `/files/preview` route unification (closed 2026-06-14):**
  `579a2fe8` on `bugfix/v1.18.8`. Both preview routes (path-based in
  `files.py`, id-based in `file_serve.py`) now delegate to one shared
  `render_office_preview()` helper → ONE JSON shape (`type`, `kind`,
  `libreoffice_available`, `total`, `name` always present) and ONE
  failure mode (LibreOffice missing → **200 text_fallback**, never the
  id-route's old 503; legacy `.ppt`/`.doc` → typed message, not a 500).
  id route derives the office ext from `meta.name`/`media_type` (content-
  addressed `meta.path` may lack one). Guard: `TestUnifiedPreviewContract`
  in `test_files_preview_download.py` (runs without office libs via mocked
  probe); 70 passed / 5 office-lib-skipped across preview suites. Unblocks
  future VSCode office-preview delegation. v1.18.8 Phase F (2/3).

- **Item 25 — `/files/read` type-contract consumers (closed 2026-06-14):**
  `2a22807c` on `bugfix/v1.18.8`. Kept the typed server contract (option b);
  fixed every consumer to branch on `type`: `CodeEditorView` refuses any
  non-`text` type (no more base64-as-text / corrupt-on-save), RPF
  save/restore gained the `office` viewType (round-trips `OfficeFileView`),
  the `typeof OfficeFileView !== 'undefined'` deploy-skew guard was dropped
  (errors visibly now), and VSCode `httpClient.readFile` got the real
  `ReadFileResponse` union + branch-on-`type` warning (contract-only, zero
  callers). Guard: `TestReadOfficeTypeContract` in `test_files_route.py`
  (csv/xlsx→office_spreadsheet base64; txt→text+lines; pptx/docx→400 hint).
  Web DOM = manual-smoke (no JS harness); `tsc`/`node --check` clean.
  v1.18.8 Phase F (1/3).

- **Item 30 — coding auto-route notice lost cross-client (closed 2026-06-14):**
  `0f21cee1` on `bugfix/v1.18.8`. `_execute_ai_task` no longer `console.print`s
  the "Auto-routed to <model>" notice (invisible to web/VSCode server-side);
  it rides in `AIResponseResult.content` (the field those clients render —
  they fall back to `message` only when content is empty). Code-block
  extraction runs on the raw output first. Other `console.print` sites in
  the function are live-TUI UX or already in the result. Guard:
  `tests/test_coding_autoroute.py`. The broad agent/utility/handler sweep is
  tracked separately as **open Item 33** (v1.19.x). v1.18.8 Phase E.

- **Item 31 — direct `session.messages` mutation bypasses AppState (closed 2026-06-14):**
  `44bb5dea` on `bugfix/v1.18.8`. Added `SessionManager.pop_orphan_trailing_users()`
  (replaces the `streaming.py` orphan-cleanup loop — now fires the
  `on_messages_changed` callback; the loop fired none before) and a
  `preserve_trailing_user()` context manager (wraps the `chat.py` preflight
  detach/restore — transient no-op, the inner `validate_and_fix_alternation`
  notifies). chat.py post-tool prompt removal routed through the existing
  `remove_last_message()` (also fixes a latent multimodal-cache miss).
  Behaviour preserved (`chat.py:273` already netted to a no-op). Guard:
  `TestMessageMutationHelpers` in `test_session_persistence.py`. v1.18.8 Phase C.

- **Item 32 — command envelope can carry non-JSON objects (closed 2026-06-14):**
  `439a0325` on `bugfix/v1.18.8`. `ConfirmationResult.to_dict()` now runs
  `details` through a recursive `_jsonsafe()` (dataclass→`to_dict()`/`asdict`,
  bytes→marker, unknown→`str`), so the HTTP envelope is always
  `json.dumps`-able. The raw-`Message` `/load` key is preserved for the
  in-process Textual renderer (which never calls `to_dict()`) — audit
  correction: it was **not** consumer-free as first flagged. Guards:
  `test_command_envelope_serialization.py` + parametrized
  `test_to_dict_is_json_serializable` over every `CommandResult` subclass.
  v1.18.8 Phase B.

- **Item 27 — `/files/image/` home-confinement (closed 2026-06-14):**
  `7fb83d8b` on `bugfix/v1.18.8`. `serve_image` swapped
  `str(path).startswith(str(home_dir))` → `_within_tree(path, home_dir)` —
  the third confinement site, which the v1.18.7 fix `09eae96e` had missed
  (it migrated `read_file`/`write_file` only). `TestServeImageConfinement`
  added (sibling-prefix path → 403 via `/files/image/`, verified to fail
  404 against the old check; in-tree image → 200). v1.18.8 Phase A — see
  [archive/plan-v1.18.8-files-parity.md](archive/plan-v1.18.8-files-parity.md).

- **Item 20 — v1.19.x alignment paperwork (closed 2026-05-24):** merged to
  master as `56bc2d38` (Stage-2 fold rebased from `42ed8f00`) + `7a2ea268`
  (C5 §13 + `AGENT_SERVICE_DOWN`) + `45e352fe` (ROADMAP "Pending alignment
  paperwork" subsection removal). Folds all consumer caveats C1–C5 and asks
  A1–A3 into ADR 0003 §6–§13 with Phase 1/5/7 ROADMAP commitments inline.
  `feat/agent-platform-stage-2` (Phase 1 implementation branch) is now
  unblocked.

- **v1.18.3 branch (closed 2026-05-02):** Items 12 (Node.js 20 → v5),
  13 (release.py step 14 silent-failure), 15 (`deploy/shared/AGENTS.md`
  stale copy), 16 (throttle counters in `/usage`), 17 (qwen3-coder-480b
  excluded after rerun confirmed contamination), 18 (NIM probe rerun),
  19 (Qwen3.5 `enable_thinking` config example), plus Tier 1 #1-3 and
  Tier 2 #4-5 from the v1.18.3 NIM engine work. See
  [docs/archive/DEBT-INVENTORY-v1.18.3.md](archive/DEBT-INVENTORY-v1.18.3.md).

- **v1.18.2 branch (closed 2026-04-29):** Items 1 (god-node refactoring
  narrowed to session_restore_ops), 2 (resolveWebviewView contract
  refactor), 4 (focused-subtree graphify runs), 5 (esbuild VSIX bundle),
  6 (Windows `code` CLI shim), 7-9 (Tier 1 observability), 10
  (EngineClientProtocol), 11 (agent.py logger AttributeError). See
  [docs/archive/DEBT-INVENTORY-v1.18.2.md](archive/DEBT-INVENTORY-v1.18.2.md).

---
