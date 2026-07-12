# Known Issues

Tracked blockers that affect production behavior or have caused regressions.
Each entry includes root cause, workaround status, and upgrade/resolution criteria.

---

## [KI-001] google-genai SDK ≥1.57.0 — Code Editing Regression

**Status:** RESOLVED BY UPGRADE (2026-07-11) — SDK raised to 2.11.0, ceiling-pinned `<2.12.0`
**Detected:** February 8, 2026
**Affected versions:** google-genai 1.57.0 through at least 1.65.0 (observed Feb 2026). **Not reproducible on 2.11.0**: the 2026-07-11 benchmark gate ran 3× on gemini-2.5-flash — code editing **100% in all three runs** (was 0% on 1.62.0), overall 70.2–74.4% vs 68.6% for the prior same-suite run on 1.56.0. The upstream v1.57.0 change was never reverted (full changelog sweep to 2.11.0), so the healing happened elsewhere in the SDK/stack — treat the regression as version-specific, keep the ceiling pin and the benchmark gate for every future raise.
**Upstream tracking:** **none.** Upstream shipped the behavior deliberately as a fix ("keep the history in chat when the API yields such a part", commit [`215c852`](https://github.com/googleapis/python-genai/commit/215c8524659c0b2ca945b6cd7887b3501db61be4)); no upstream issue tracks this regression. [#1789](https://github.com/googleapis/python-genai/issues/1789) (empty finish message on MALFORMED_FUNCTION_CALL — still open) and [#1818](https://github.com/googleapis/python-genai/issues/1818) (AFC config persistence — closed as not planned) are **related-but-different** bugs from the original v1.15.3 analysis; an earlier revision of this entry wrongly promoted them to the upgrade gate. Waiting on them can never signal a fix — the only valid gate is our own benchmark (below).

### What broke

Upgrading from SDK 1.56.0 → 1.62.0 caused a **-12.5% overall benchmark regression** on gemini-2.5-flash, with code editing dropping from **57.1% → 0%** — a complete failure.

| Metric | SDK 1.56.0 | SDK 1.62.0 | Delta |
|--------|-----------|-----------|-------|
| Overall score | 76.6% | 64.1% | **-12.5%** |
| Code editing | 57.1% | 0% | **-57.1%** 🚨 |
| Hallucination resistance | 55.6% | 33.3% | -22.3% |
| Tool calling | 85.7% | 85.7% | no change |

### Root cause

**SDK v1.57.0** (Jan 7, 2026) removed validation restrictions on empty text parts:

> "Remove validation for empty text parts on Chat, this will support keeping the history in chat when the API yields back such a part."

This change lets incomplete responses (empty or whitespace-only text parts) pass through unchecked, causing the model's actual code output to be silently swallowed.

### Workarounds in place

**1. Version pin (ceiling)** — `pyproject.toml` constrains both optional and
dev dependencies to the last benchmark-verified version:
```toml
"google-genai>=1.0.0,<2.12.0"
```

**2. ~~Defensive filter~~ — dead code, DELETED (2026-07-12).**
`_filter_empty_parts()` in `ppxai/engine/providers/gemini.py` was believed to
strip empty text parts from the response paths as a safety net. A source
sweep found it had **zero call sites** — the v1.15.3 call sites were lost in
a later refactor, so no filter was active for any of the verdicts above.
(This also means the 2.11.0 benchmark pass was achieved with NO mitigation in
the path — stronger evidence for the SDK itself.) Resolved via
[debt Item 41](debt-inventory.md): the function is deleted (the response
parse loops skip empty text parts inherently), a sentinel test in
`tests/test_gemini_native_tool_loop.py` pins the deletion, and the same
change wired Gemini's native function_call/function_response transcript
threading. Post-change gate 3× gemini-2.5-flash on 2.11.0: code editing
100/100/100, overall 80.7/72.6/73.8.

### How to verify before upgrading (benchmark gate — the ONLY gate)

There is no upstream signal to wait for (see **Upstream tracking**), and no
code-side mitigation is active (see #2 above) — only the benchmark can prove
a candidate version:

1. Bump the pin in `pyproject.toml` (both the `gemini` extra and the main
   deps carry it) to the candidate version and run `uv lock` + `uv sync --all-extras`.
2. Run the Gemini unit suites first (cheap gate):
   `pytest tests/test_gemini_tool_schema.py tests/test_gemini_null_parts.py tests/test_gemini_extras.py`.
3. Run the benchmark suite (3 separate invocations — there is no `--runs`
   flag) against gemini-2.5-flash (or gemini-3-flash-preview):
   ```bash
   cd benchmarks/llm-eval && python benchmark.py --provider gemini --model gemini-2.5-flash
   ```
   Beware free-tier rate-limit contamination — throttled runs read as fake
   quality regressions.
4. Verify code editing score ≥50% and overall score ≥75%.
5. If passing, raise the ceiling to the verified version (e.g. `<2.12.0`) —
   do NOT remove the upper bound entirely; this SDK has regressed us before,
   so every ceiling raise goes through this gate.

### Upstream review log

- **2026-07-11 (verdict)**: pin raised to `<2.12.0`, locked at 2.11.0.
  Benchmark gate 3× gemini-2.5-flash: code editing 100/100/100%, overall
  74.4/70.2/74.4% (prior same-suite run on 1.56.0: 68.6%; the ≥75% figure in
  the gate was calibrated to the old 26-test suite — today's suite has 36
  tests incl. agentic_tool_loops + efficiency). Gemini unit suites 34/34.
  Note: the Feb rollback log shows `_filter_empty_parts()` did NOT fix the
  0% on 1.62.0 (only the rollback did). Corrected 2026-07-12: the filter is
  not even defense-in-depth — it has zero call sites (dead code since a
  post-v1.15.3 refactor; debt Item 41) — so it cannot be the reason 2.11.0
  passes. Later the same day it was deleted outright (Item 41 resolution)
  and the gate re-run 3× post-deletion + native tool-transcript threading:
  code editing 100/100/100, overall 80.7/72.6/73.8 — the pin verdict holds.
- **2026-07-11** (SDK at 2.11.0, released 2026-07-09): change not reverted;
  no GenerateContent-surface breaking changes in 1.57.0→2.11.0 (all breaking
  entries scoped to the Interactions/Agent-Platform surface; v2.0.0 notes
  explicitly disclaim GenerateContent impact). AFC breaking change announced
  in 2.8.0 docs — ppxai does not use automatic function calling. Classic
  `Schema` still rejects `oneOf` (only Agent-Platform `JSONSchema` gained
  `one_of` in 1.74.0) — the `_sanitize_schema_for_gemini()` downgrade in
  `gemini.py` stays required at any version;
  `tests/test_gemini_tool_schema.py` pins both directions.

### Archive

Full analysis, workaround implementation notes, and rollback log:
- `docs/archive/v1.15.3/GEMINI-SDK-REGRESSION-ANALYSIS.md`
- `docs/archive/v1.15.3/GEMINI-SDK-WORKAROUNDS-APPLIED.md`
- `docs/archive/v1.15.3/GEMINI-SDK-ROLLBACK-STATUS.md`

---

*Add new entries above using the `[KI-NNN]` format.*
