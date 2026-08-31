# Item 65 — implementation plan (auditor → builder)

**Written 2026-08-31 by the auditor session (ppxai-28) for the builder
(ppxai-c7), against branch `bugfix/v1.19.1` @ `4b49e960`.**

Item 65 = retire `BUILTIN_PROFILES` as the seed vocabulary for
`ModelFacts`. Debt entry: `docs/debt-inventory.md` §Item 65.

This file is the durable record. Every number below was derived by
running against the tree at `4b49e960`, not recalled — re-derive before
trusting it if the branch has moved.

---

## 0. Sizing correction (supersedes an earlier auditor claim)

An earlier read reported `ModelProfile` at 85 refs and
`ToolCallingProfile` at 75, and inferred that retiring the types was the
larger share of the work. **That was wrong** — it counted raw grep hits
without separating self-references inside the defining module.

| Symbol | In `model_profiles.py` | External prod | Tests |
|---|---|---|---|
| `ModelProfile` | 79 | **3** | 25 |
| `ToolCallingProfile` | 67 | **2** | — |

Four of those five external production references are **prose in
docstrings/comments**. The only real code import is
`ppxai/engine/model_facts.py:74`. Deleting the types is nearly free once
the data moves; **re-authoring the 65 rows is the whole job.**

---

## 1. The one field that can silently change meaning

`ToolCallingProfile.mode` defaults to `"native"`.
`ModelFacts.tool_mode` defaults to `"prompt_based"` (ADR 0012 Q0a
deliberately inverted it: "unmeasured implies assume not capable").

Measured distribution across the 65 rows:

    native: 52   prompt_based: 11   auto: 2

So ~52 rows currently rely on the *profile's* default and would flip
meaning under mechanical transcription.

> **RULE: every re-authored row states `tool_mode` explicitly.**
> No row inherits the `ModelFacts` default.

The comment at `model_facts.py:194-199` argues code rows *may* rely on
dataclass defaults. That holds while rows are generated; it stops
holding the moment a human types them.

---

## 2. `wire_protocol` is not in the seed rows — 15 rows need it stated

Today it is supplied by two mechanisms *outside* `BUILTIN_PROFILES`:
`_API_PATH_TO_WIRE` (3 rows with `api_path="responses"`) and
`_WIRE_BY_GLOB` (12 gemini/gemma globs to `generate_content`).

Transcription checklist — each must appear as an explicit
`wire_protocol=` on its re-authored row:

**`responses` (3):**
`gpt-5.3-codex*`, `gpt-5.1-codex-mini*`, `gpt-5.1-codex*`

**`generate_content` (12):**
`gemini-2.5-pro*`, `gemini-2.5-flash-lite*`, `gemini-2.5-flash*`,
`gemini-3.5-flash*`, `gemini-3-flash*`, `gemini-3.1-flash-lite*`,
`gemini-3.1-pro*customtools*`, `gemini-3.1-pro*`,
`gemma-4-31b*`, `gemma-4-26b*`, `gemma-4-e*`, `gemma-4*`

The remaining 50 take the `chat_completions` default, which matches.

**Live migration pressure:** the 2026-08-31 fleet refresh established
that the whole gpt-5.6 line needs `wire_protocol: responses` (it 400s on
a tools array alone over chat-completions). That is currently expressed
in **config only**. Check whether a `gpt-5.6*` glob belongs in the
re-authored shipped table rather than living only in config.

---

## 3. Two different `auto` values — do not conflate

- `api_path="auto"` — *documented but never implemented*. Maps to
  `chat_completions` because mapping it to a handler name would route to
  one that does not exist. After migration `_API_PATH_TO_WIRE`
  disappears, so **this decision must survive as an explicit row value
  plus a comment**, or the knowledge is lost.
- `tool_mode="auto"` — a different field, and this one **is**
  implemented. 2 rows use it.

---

## 4. Reference-data validation pass (owner-approved addition)

Owner asked that published model data (HF / publisher model cards) be
used to sanity-check seeded values rather than transcribing blind.

### 4a. What was probed and REJECTED

The original framing — "fill in default guesses from published profiles
where we have no measured data" — does not survive contact with the
table. Two findings, both verified:

1. **All 65 rows carry a benchmark tier** (S:8, A:16, B:24, C:14, D:3).
   There is no unmeasured row. The premise does not hold here.
2. **`max_tokens: 0` / `max_tool_iterations: 0` are not missing values.**
   Per `model_profiles.py:57`, `0` means *"use provider default"* — a
   deliberate delegation. 6 rows are `0` on `max_tokens`, 41 on
   `max_tool_iterations`.

The 5 rows unstated on BOTH limits are all open-weight VL **globs**:
`*qwen3-vl*`, `*qwen2-vl*`, `*llava*`, `*pixtral*`, `*minicpm-v*`.

A glob has no single published number. `*minicpm-v*` matches
MiniCPM-V / V-2 / V-2_6 / V-4_5 / V-4.6, whose published context lengths
run 4K to 32K to 64K to 262K. `*pixtral*` matches Pixtral-12B (128K) and
Pixtral-Large. Verified by search 2026-08-31.

Worse, the quantities differ in kind: HF publishes **context window**
(input capacity); `max_tokens` is an **output cap**. Conflating them
turns a 128K context into a nonsense 128K output request.

> **DO NOT fill these five.** Re-author them as `0`, with a comment
> stating that `0` means provider-delegation for a family glob. This
> turns an apparent hole into documented intent.

### 4b. What to actually validate against published data

Three fields where publisher data genuinely decides something:

1. **The 15 `wire_protocol` rows (§2).** Hard fact about which endpoint
   serves a model; wrong means requests break outright. The gpt-5.6 line
   already proved the failure mode.
2. **The 23 `supports_vision: False` rows.** This flag routes images
   through a VL sidecar vs. sending natively
   (`ppxai/engine/file_preprocessing.py`). A wrong `False` **silently
   degrades output** rather than erroring — the worst failure shape.
3. **The 14 `restricted_params` rows** (all `('temperature','top_p')`).
   Publisher-documented; wrong means hard API rejection.

All three are unambiguous in a model card, unlike a context number.

Any correction found lands as **its own commit**, separate from the
transcription — so the byte-identical check in step 1 stays meaningful.

### 4c. Provenance (owner to confirm scope)

No row records *where its value came from*. That is precisely Item 63
("benchmark conclusions are hand-typed into code, unlinked and
unchecked"). A `source` comment per re-authored row would make the next
refresh checkable. **Open question: in scope for Item 65, or deferred to
Item 63?** Do not decide this unilaterally.

---

## 5. Sequencing — two commits, deliberately

**Step 1 — re-author, delete nothing.**
Replace the `SHIPPED_MODEL_FACTS` dict comprehension with 65 literal
`ModelFacts(...)` rows. Keep `BUILTIN_PROFILES` and the flattener in
place.

This is the whole reviewable data diff, and the existing fence proves
it: `tests/test_model_facts_are_the_source.py`
::`test_every_profile_row_flattens_to_its_facts_row` compares each
literal against the flattened original **field for field**. Green means
byte-identical semantics.

`test_the_seed_table_is_still_the_expected_size` asserts
`len(BUILTIN_PROFILES) == 65`. It should keep passing through step 1
(seed table untouched); step 2 retires it.

**Step 2 — delete the bridge, separate commit.**
Remove `ModelProfile`, `ToolCallingProfile`, `facts_from_profile`,
`_seed_row`, `_wire_for`, `_API_PATH_TO_WIRE`, `_WIRE_BY_GLOB`,
`BUILTIN_PROFILES`, and `model_profiles.py` itself if nothing else lives
there. Retarget the ~25 test refs and 4 prose mentions.

The comparison fence loses its left-hand side. **Rewrite it, do not
delete it** — as invariants over `SHIPPED_MODEL_FACTS`: row count, every
row states `tool_mode`, the 15 known non-default wires.

Two commits is what makes step 1 reviewable — the same argument the debt
item makes for why this was kept out of W4.

---

## 6. Defect found while planning (fix in step 2)

`facts_from_profile`'s docstring (`model_facts.py:221-224`) says it is
*"the migration helper `/doctor` uses to show an operator what a legacy
row becomes."*

Grep across `ppxai/` and `tests/` finds **no `/doctor` caller**. The only
production call site is `_seed_row`, in the same file. Either the feature
was never built or it was removed, and the docstring is now the sole
evidence for a capability that does not exist — the same "declared is not
consumed" shape that produced Item 61. It gets deleted in step 2 anyway,
so correcting the record costs nothing.

---

## 7. Ground rules

- Owner approved this plan 2026-08-31, explicitly allowing a second
  iteration if issues surface. Surface them rather than improvising.
- §4c is an open owner question. Do not settle it in code.
- Derive counts; never restate one from this file without re-running it.
