# A trailing-streak, byte-exact loop guard detects almost nothing real models do

**TL;DR:** A guard that only counts a **trailing streak** of **byte-identical**
arguments misses the loop shape models actually produce — paraphrased
repeats interleaved with other calls — and both properties had to go: count
occurrences anywhere in the turn, and add an argument-independent budget.

**Verify with:** `git show 2514ba55^:ppxai/engine/tools/manager.py` — the
retired `is_tool_loop_detected` (then at line 519) walked
`reversed(self._tool_call_history)` and `break`s at the first non-matching
call, so one differing call anywhere resets the count to zero. Compare
against the current `is_tool_loop_detected`
(`ppxai/engine/tools/manager.py:591`), which sums matches over the whole
turn instead, and `_hash_args` (`ppxai/engine/tools/manager.py:548`), which
is unchanged: `json.dumps(args, sort_keys=True, default=str)` — still
byte-exact, so two differently-worded queries still count as different
calls.

## Why this trips people up

"Detects the same tool called repeatedly" sounds like one property. It is
two, and a guard can satisfy either without satisfying both:

- **Exact-match** on arguments — catches `get_weather(city="Boston")` called
  twice, misses `get_weather(city="Boston, MA")` right after.
- **Trailing-streak** counting — catches three calls in a row, misses three
  calls spread across a turn with anything else between them.

A model in a real loop rarely repeats an identical call back-to-back N
times; it rephrases. The 2026-09-22 incident measured this directly: one
turn ran `web_search` 15 times in 113 seconds hunting one IMDb image id,
every call succeeding, "Loop detected" logged **zero** times. Four of the
fifteen queries were byte-identical, but interleaved with ten paraphrases —
never three in a row — so the trailing-streak counter reset before it ever
reached the threshold of 3.

## What to do

1. **Count per turn, not per streak.** `is_tool_loop_detected` now sums
   `record.tool == tool_name and record.args_hash == args_hash` over the
   whole turn's history (`manager.py:591-624`), instead of walking
   backward and resetting at the first mismatch. The old streak rule was
   deleted rather than kept as an earlier-firing check beside it: a
   trailing streak of N is also N occurrences in the turn, so it can
   never fire before the occurrence count does — keeping it would have
   been dead code.
2. **Add an argument-independent per-tool budget for retrieval tools
   only, generous.** `is_tool_budget_exceeded` (`manager.py:645`) caps
   `web_search` and `fetch_url` at 10 calls per turn by default
   (`Default.TOOL_CALL_BUDGETS`, `ppxai/constants.py:242-245`; absent or
   0 = unlimited; every other tool stays uncapped). This is the guard
   that catches the incident's ten *paraphrased* calls, which
   exact-match matching structurally cannot see no matter how it counts.
   The number comes from tau-bench's published trajectories
   (`sierra-research/tau-bench`, 1,960 real GPT-4o/Sonnet runs scanned
   locally): one tool is called once in 83.6% of turns and five times or
   fewer in 99.3%, but 32 of the 76 turns that called one tool six-plus
   times were successful (reward 1.0) — a low cap would have cut real
   work.
3. **Exclude failed calls from both guards.** `record_tool_call`
   (`manager.py:562`) only increments guard B's count, and only appends a
   `success=True` record for guard A to match against, when the call
   actually succeeded. A retry after a transient failure is recovery,
   not a loop — telling a model to "synthesize from the results you
   already have" is wrong advice when there are no results, and a tool
   that keeps failing is the zombie circuit breaker's job, not this
   guard's.
4. **Give each trip its own user-visible text.** `get_loop_message`
   (guard A) and `get_budget_message` (guard B, `manager.py:679`) are two
   different strings. The old single message said "called Nx with same
   args" — reusing it for a budget trip would tell the model its
   arguments were the problem, so it rephrases, which is the paraphrase
   loop guard B exists to stop.
5. **Make the refusal terminal.** A second attempt at an already-budget-
   exhausted tool sets `force_synthesis = True` (`ppxai/engine/chat.py`,
   in `chat_with_tools`'s `if budget_refusals[tool_name] >= 2:` block —
   line 998 as committed at `2514ba55`), which withdraws all tools for
   the rest of the turn and forces a synthesis pass. Without this, a
   model that doesn't take the hint burns every remaining iteration
   re-offering arguments to a tool that will never run again this turn.
   Guard A (the repeat rule) has **no equivalent escalation** — only
   guard B's budget trip is terminal; see Item 80 in
   `docs/debt-inventory.md` for the gap this leaves.

A guard limited to only the old two properties (exact-match, trailing
streak) is provably weaker than the five-item version above — it is a
strict subset of what the per-turn, budgeted, escalating guard catches.

## What NOT to do

**Fuzzy/semantic argument matching was considered and declined.** It needs
a tuned per-tool similarity threshold, and it blocks two deliberately
different queries as readily as one rephrased one — there's no threshold
that reliably tells "same hunt, reworded" from "genuinely next question."
The accepted gap this leaves — an alternating two-tool cycle with
non-repeating arguments (`A, B, A, B, …`, never twice with the same
arguments) — is recorded in
`tests/fixtures/tool_loops/call-graph-cycle-alternating-distinct-args.json`
rather than hidden, and is bounded only by the iteration cap and the
zombie circuit breaker.

## Related

- [a-check-that-never-ran-reports-success.md](a-check-that-never-ran-reports-success.md) —
  same family of trap: a guard that looks like it's checking something but
  structurally cannot see the failure mode in front of it
- [mutation-tests-that-never-ran.md](mutation-tests-that-never-ran.md) —
  the trailing-streak rule is the same shape as a mutation on an
  unreachable line: it "worked" on every case anyone tested it against,
  because no test constructed an interleaved repeat
