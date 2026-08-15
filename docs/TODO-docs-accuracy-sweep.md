# TODO — documentation accuracy sweep (v1.19.1)

**Status:** ✅ **COMPLETE** — all 7 phases + the lower-severity remainder
executed 2026-08-15 on `bugfix/v1.19.1`, one commit per phase
(`421e381c` P0 · `b7c6b527` P1 · `20c695ab` P2 · `7698bd75` P7 ·
`0b3bde98` P3 · `66639086` P4 · `7bec4940` P6 · `575ae3e7` P5).
Filed 2026-08-15 @ `7c82c95e`.

**Two filed findings were REJECTED on verification** (in addition to the
macOS-Intel one at the bottom) — do not re-file:
1. *"`autorouter-config.md:30` names the wrong OpenAI coding model."*
   False: it names `gpt-5.4-mini`, which **is** `providers.openai.coding_model`
   in `ppxai-config.json`.
2. *"The `strip_orphan_tool_calls` grep in the Perplexity lesson no longer
   resolves."* Half false: it still resolves in `engine/session.py:29`. Only
   the **chat.py** grep was stale (that file now calls the composed
   `sanitize_outbound`), and only that half was corrected.

The widened ADR-0010 sentinel found **four more** cases on its first run that
no reviewer had filed: `AGENTS.md:530`, `scripts/trial-task-lifecycle.py:21`,
and five stale version stamps.
**Scope:** repo documentation only — no production-code changes except where a doc
fix requires confirming behavior.

## How to use this document

Work the phases in the recommended order below. Every finding cites `file:line` for
both the wrong claim and the evidence. **Re-verify before editing** — this file is a
point-in-time snapshot and the tree moves. When a phase lands, mark it ✅ here in the
same commit.

**Method that produced it:** four parallel reviews (top-level files / user guides /
process+lifecycle / patterns+lessons+specialist), each required to verify claims
against source. ~93 findings retained, 1 rejected on verification (see the bottom
section — do not re-file it). Mechanical drift already fenced by
`tests/test_docs_consistency.py` (retired ADR-0011 command names, broken relative
links, phantom repo paths, legacy `tools.agent.*` key paths) was excluded from scope.

## Ground truth as of `7c82c95e` (verify anything you depend on)

- Version **1.19.1, UNRELEASED**; v1.19.0 is the latest GitHub release. 120 commits ahead of `master`.
- ADRs **0009, 0010, 0011 all Accepted AND implemented**. ADR 0010 shipped as a
  **clean break** — legacy `tools.agent.{task_tier_enabled,sandbox,spawn_consent,consent_ttl_s,result_retention_s,default_subagent}`
  moved to `execution.*` and the old paths are silently ignored, not dual-read.
- **T8b shipped** (unparked 2026-08-08). `/task` + `/run` register client-agnostically in
  `ppxai/commands/factory.py:37-40` + `ppxai/commands/task.py:440`, backed by the in-process
  `ppxai/engine/task_runner.py`. **Nuance:** Textual has full parity; **Rich lacks
  `launch`/`resume`** (they need a live event loop — `ppxai/commands/task.py:52,69-88`).
- Suite collects **5097** tests.

---

## PHASE 0 — ✅ DONE (2026-08-15) — one wrong fact, nine places

Every "web + VSCode only" / "T8b parked" claim is false (see ground truth above).
All nine below are fixed, plus four spots the review missed: ADR
`0011-command-taxonomy-streamline.md:172` (annotated *Resolved*, ADR body kept
historical), `plan-run-taxonomy-sequencing.md:192`, and three live references to
the retired key (`tools.agent.task_tier_enabled` -> `execution.task.enabled`)
**outside `docs/`** — `scripts/gateway-smoke.py:16,758` and
`.claude/skills/build-install/SKILL.md:562` — which survived precisely because
the ADR-0010 sentinel only scans `docs/`
(Phase 7 item 2, now empirically confirmed; widen it to `scripts/` and
`.claude/` too). `docs/release-notes-v1.19.0.md` and the `CHANGELOG` `[1.19.0]`
section were left alone on purpose: they are historical records that were
accurate at their release.

| File:line | Claim to fix |
|---|---|
| `CLAUDE.md:25` | "Surface split: `/run` and `/task` exist in **web + VSCode only** … until the parked T8b transport decision lands" |
| `CLAUDE.md:29` | "T8b (TUI port) is ⏸️ PARKED (2026-07-07)" |
| `README.md:235` | "Ships in **Web** and **VSCode**" |
| `docs/task-agent-guide.md:3-6` | "Clients: Web + VSCode (TUIs: not yet…)" |
| `docs/session-agent-guide.md:13-14` | surface table lists `/run`//`task` as Web+VSCode |
| `docs/agent-task-command-design.html:152` | "The TUI port (T8b) is parked pending a transport decision" |
| `docs/agent-task-command-design.html:257` | "**Parked:** TUI port (T8b)" |
| `docs/plan-task-command-sequencing.md:500` | "T8b — ⏸️ PARKED (2026-07-07 — resume here)" — contradicts its own `:568` |
| `docs/archive/plan-v1.19.0-sequencing.md:3-7` | banner "T8b is parked" |

Also `docs/plan-task-command-sequencing.md:568` header still says "🚧 IN PROGRESS" —
`f3cf3d53` and `394bdf1f` closed the remaining gaps; it is DONE.
And `docs/archive/plan-v1.19.0-sequencing.md:11` still says "**Status:** Active" three lines
under a "CLOSED" banner.

## PHASE 1 — ✅ DONE — top-level files

| # | File:line | Sev | Issue | Fix |
|---|---|---|---|---|
| 1-3 | see Phase 0 | High | T8b | Phase 0 |
| 4 | `CLAUDE.md:13` | Med | "two implemented ADRs" — it's **three** (0009, 0010, 0011) | say three |
| 5 | `CLAUDE.md:60` | Med | "4,796 passing … verified 2026-08-04 @ `2aa3669b`" | 5,097 + fresh date/commit |
| 6 | `CLAUDE.md:27` | Med | "Legacy keys they supersede are dual-read" — only `execution.run.grounding` dual-reads (`ppxai/config/execution.py:56-60`); `execution.task.*` is a clean break and is omitted from the axis rundown entirely | scope the dual-read claim, add `execution.task.*` + "no dual-read" |
| 7 | `README.md:164` | Low-Med | Gemini list names 2.5 Pro / 3-Flash Preview — absent from `ppxai-config.json:143-172`; omits `gemini-3.1-flash-lite` + both Gemma 4 | sync to shipped catalog |
| 8 | `README.md:165` | Low-Med | "GPT-5.4 (default)" — real default `gpt-5.4-mini` (`ppxai-config.json:217`); names `gpt-5.1-codex` (absent; real is `gpt-5.3-codex`) + o-series (absent); omits GPT-5.5/5.5-pro | sync to shipped catalog |
| 9 | `README.md:3,475` | Low | badge `tests-4796` | leave to `/release` (badge trails by design) |
| 10 | `README.md:226` | Low | `/task` has a full subsection; `/run` never does | add a short `/run` subsection |

No findings: ROADMAP.md, AGENTS.md, BUILD.md, CONTRIBUTING.md, SECURITY.md,
SPECIFICATIONS.md, RELATED-PROJECTS.md, CODE_OF_CONDUCT.md.

## PHASE 2 — ✅ DONE — release paperwork (blocked any release)

1. **`docs/release-notes-v1.19.1-DRAFT.md` is ~40 commits stale** (last touched `573b76ff`,
   2026-08-06). Missing: security/admission-boundary unification (`135abf48`), the entire
   `network.ssl.*` + outbound-TLS-resolver feature and its review fixes (`f9dff325`,
   `ccdd0f3f`, `7c82c95e`), Gemini `response_format`/grounding fixes (`f72c10c7`,
   `23d8695a`), T8b shipping, Items 56-59, `5e80b8d7`, `cf4791d3`, `3acc90ae`,
   `41e709f6`, rtk bump. `/release` renames this file into the shipped notes.
   **Backfill from `CHANGELOG.md`.**
2. **`CHANGELOG.md [1.19.1]` never states T8b shipped as a feature.** Its only T8b
   mentions (lines 129/137/142) sit inside *Security*, describing a bug T8b launched
   with. Add an explicit Added/Changed bullet.

## PHASE 3 — ✅ DONE — actively-wrong user guides (High)

| File:line | Issue | Evidence |
|---|---|---|
| `docs/api-gateway.md:531` | "Native … **no run record**" — contradicts its own `:416-420` | `ppxai/server/routes/oneshot.py:597` calls `registry.start_run(kind="oneshot")` |
| `docs/consent-contract.md:225` | spawn_consent `deny` = "refused outright — no callback, no park" | `ppxai/engine/tools/agent_spawn.py:178-186,314-323` parks as `waiting{consent}`, denies on TTL; contradicts doc's own `:223` |
| `docs/installation.md:964` | "get_weather falls back to HTTP when HTTPS fails" | removed by ADR 0009 §2 / Item 52 — `ppxai/engine/tools/builtin/web.py:60-65` |
| `docs/provider-setup.md:105` | Gemini example uses `gemini-2.5-flash`/`-flash-lite` | both past shutdown — `ppxai/engine/model_deprecations.py:85-93` |
| `docs/index.md:79` | Tab completion `N/A` for VSCode + Web | `ppxai/server/routes/completion.py:39`, `vscode-extension/src/chatPanel.ts:828-851` |
| `docs/shell-wrappers.md:104,130` | `enabled:"always"` "raises a clear error if binary missing" | silently no-ops — `ppxai/engine/tools/wrappers/base.py::is_active()` ignores PATH (own test `test_is_active_always_ignores_binary`) |
| `docs/container-tools-guide.md:150,609` | logs 60s vs list/inspect 30s — **reversed** | `ppxai/engine/tools/builtin/container.py:96` default 30s; 60s is `ConsentCLITool`. ⚠️ introduced by docs-sweep `46c7c255` itself |
| `docs/shell-consent-guide.md:259` | `tools.shell.sandboxed_paths` presented as enforced | parsed (`ppxai/config/tools.py:88`), never read — inert |
| `docs/patterns/transactional-state.md:~68-72` | claims `status_bar.transaction()` is live for provider/model switch + session restore | only 3 call sites, all in the `/badge` demo (`ppxai/tui/app.py:~1357`); real restore is sequential best-effort (`ppxai/engine/session_ops.py:20`); no test references `BadgeTransaction` |
| `docs/vllm-tool-calling-guide.md:459-479` | "native tool calling now safe for GPT-OSS (vLLM PR #30205+)" | `ppxai/engine/model_profiles.py:657-661` forces `prompt_based`; `ppxai/engine/chat.py:693-694` overrides capability flags; upstream issue #23567 open |
| `docs/decisions/README.md` | has **no ADR index at all** — pure process prose | add a table of all 11 ADRs with status |

## PHASE 4 — ✅ DONE — dev guides taught broken code

`docs/custom-command-development-guide.md`:
- `:309` `handler.engine_client.working_dir` → **AttributeError**; real API `get_working_dir()` (`ppxai/engine/client.py:539`)
- `:87-91` "return True → exit the application" — false; `/quit`//`exit` are hardcoded pre-dispatch (`ppxai/commands/handler.py:575-590`)
- `:3` "works with both Rich and Textual" — the taught style (`console.print`, `handler.theme`) is Rich-only
- `:597` documents default `category="custom"`; real default is `"general"`. Examples at `:706-814` use `git`//`notes`//`tools`, but `reload_user_commands()` only unregisters `category="custom"` (`ppxai/commands/factory.py:402-437`) → **zombie commands after `/reload`**
- `:104` `aliases: List[str] = []` in a dataclass → `ValueError`; real code uses `field(default_factory=list)`
- missing entirely: the real `CommandContext`/`CommandResult` pattern (used by `/reload` itself)

`docs/custom-tool-development-guide.md`:
- teaches `if TYPE_CHECKING:` imports — violates the repo's standing no-TYPE_CHECKING rule
- `:633,791` `/tools list` "Source" column doesn't exist (`ppxai/commands/tools.py:146-176`)
- `:609` drops the required `engine` arg; `:1132` version footer stale
- no mention of `tools.<tool>.egress` / `execution.egress_ceiling` despite network-tool examples

## PHASE 5 — ✅ DONE — missing documentation for shipped features

- **`network.ssl.*` has zero user-facing coverage** — absent from README, `docs/index.md`,
  `docs/README.md`, `known-issues.md`, `dev-setup.md`. `installation.md:952-974` covers only
  env vars, not the persistent config keys (`ppxai/config/tls.py:130-181`);
  `provider-setup.md:508` never mentions `network.ssl.cert_file` though `/doctor`
  (`ppxai/commands/doctor.py:204-209`) recommends it.
- `/doctor`'s "Config shape (ADR 0010)" section (`ppxai/commands/doctor.py:671-753`) — unmentioned
- `/reload` — no coverage anywhere
- `execution.task.default_grant` / `allow_user_default` (Item 58) missing from `task-agent-guide.md:88,91,167`
- `docs/architecture.md`: no `/v1/oneshot` or `/v1/agent/*` in the endpoint table (`:771`);
  engine tree shows 5 of 36 files (`:60`); commands tree omits `task.py` (`:70`); web tree omits
  the Task/Run UI files (`:704`); ADR 0010's three-axis design never explained;
  `ppxai/config/tls.py` missing from the leaf-module list
- `docs/README.md:77-98` built-in tools table omits the office family (11 tools) + 9 container/k8s tools
- `docs/debug-logging.md:7` lists 4 log files; 13 are produced
- `docs/file-editing-guide.md` — no mention of the R13 post-write syntax validator gating all 5 edit tools

## PHASE 6 — ✅ DONE — lifecycle: archive completed docs

Move to `docs/archive/` (each self-declares completion — verify the banner before moving,
then fix inbound links):

`branch-review-v1.19.1.md` · `plan-run-taxonomy-sequencing.md` · `plan-v1.19.0-sequencing.md`
(fix `:11` "Active" first) · `plan-adr0009-step1-oneshot-enrichment.md` ·
`plan-oneshot-grounding.md` · `handoff-adr0010-k8s.md` ·
`handoff-build-task-runner-extraction.md` · `handoff-session-provider.md` ·
`exception-handling-audit.md` · `discussion-agents-framework.md` (superseded by ADR 0003).

Keep live: `handoff-seam-watcher.md` (protocol index), `handoff-a4-response.md` (unbuilt),
`mcp-integration-plan.md` (v1.20.x), `TODO-routing.md`, the release-notes rotation.
**No `docs/handoffs/` subdir needed** — archiving the completed three leaves only two.

Flag, don't move: `agent-platform-call-graphs.md` (predates the `authorize_task()` admission
unification it doesn't describe); `model-behavior-analysis.md` (self-declared "living, updated
each benchmark session", untouched ~3 months; Items 54/55 would change its rankings).

Also `docs/debt-inventory.md:1497-1502` — Item 37 letter (t) should be marked RETIRED
(cite `eeb82076`), matching how sibling (r) is already handled.

## PHASE 7 — ✅ DONE — sentinel extensions (21 → 27 tests)

Per the standing "extend the sentinel, don't re-audit" rule:
1. **T8b/surface-split fence** — fail on `web + VSCode only` and on `T8b` near `PARKED` in active docs.
2. **Scope gap found during this review:** `ADR_0010_MOVED_KEYS` scans only `docs/`, **not
   top-level files**, and omits `sandbox` from the checked keys. Widen both.
3. **Test-count drift** — assert CLAUDE.md's stated count is within N of actual collection
   (README badge exempt — it trails by design).
4. **Doc-vs-config model catalog** — assert model ids named in README/`provider-setup.md` exist
   in `ppxai-config.json` (would have caught findings 7, 8, and the Gemini 2.5 one).
5. **Stale version banners** — several guides carry `v1.11.2` / `v1.13.0` / `v1.13.10` footers
   while linked as current.

## Lower-severity remainder — ✅ DONE

`patterns/command-envelope.md` `:16` canonical envelope omits `events`, `:34` names the deleted
`TextualCommandContext`, `:27` "15 kinds" now 16 · `patterns/appstate.md:28,44` (schema-derived
now; handler is a fan-out) · lessons: `mcp-not-yet-integrated.md:29` (`.mcp.json` is now empty
`{}`), `:17` line drift; `perplexity-alternation-…:19` grep no longer resolves (now
`sanitize_outbound`); `stale-tests-outlive-deleted-behavior.md` cites renamed classes ·
`ppxaide-impl.md:114` iTerm2 widget wrong, `:92` contradicts `linux-terminal-setup.md:266-271`
on the Kitty protocol, `:30` theme count (22, not 17+) · `multimodal-api-models-reference.md:84-91`
omits `sonar-reasoning-pro`, `:75` gpt-5.4 pricing ≠ config · `vllm-notes.md:12-17` lacks a
Qwen3-Coder parser row · `docs/research/*` citing gaps already closed (`build_task_runner`
extraction; `state.json` persistence) · `autorouter-config.md:30` wrong OpenAI coding model ·
`bootstrap-context-guide.md:459,72,347` · `context-injection.md:413` ·
`file-editing-guide.md:109,668` · `model-selection-guide.md:57` vs `AGENTS.md:179-190` ·
`docs/README.md:205` "16-file package" now 17.

---

## Rejected on verification — do NOT re-file

**"macOS Intel binaries are no longer built."** A reviewer inferred this from
`.github/workflows/build.yml` having only `macos-arm64` in its matrix. **False.**
`scripts/release.py:884` marks Intel assets *"Optional Intel Mac builds (built locally, not by
CI)"*, and v1.19.0 shipped all five Intel artifacts including `ppxai-1.19.0-macos-intel.dmg`.
`docs/installation.md:268,385`, `BUILD.md:309` and `vscode-extension/README.md:45` are correct.

Minor real nit noticed while checking: `ppxaide-macos-intel` ships but is absent from
`release.py`'s `optional` asset list — cosmetic, no user impact.
