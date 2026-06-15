# ADR 0006 — Separate engine-internal content schema from wire schema

**Date:** 2026-05-14
**Status:** Accepted — full implementation lands on `bugfix/v1.18.6` (all 4 phases). No stopgap; the producer-side fix is shipping directly.
**Related:**
- [ADR 0003](0003-agent-platform-architecture.md) — agent platform (sub-agents + autonomous agents) for v1.19.x. Strategic motivation for v1.18.6's schema_version: 2 work — every architectural primitive ADR 0003 needs (run identity, persistence, cross-process readers, sub-agent message construction) inherits or extends what this ADR establishes. See "Strategic rationale" section below.
- [ADR 0004](0004-llm-gateway-features.md) — v1 API gateway; this ADR's wire-schema discipline is what makes the gateway safe across strict OpenAI-compatible endpoints
- [ADR 0005](0005-inspection-triplet.md) — runtime observability pattern; the `events.jsonl` artifact captures provider-bound payloads, so the wire-vs-internal split is also a debugging clarity win. ADR 0005 §"Open decisions" item 2 ("Event schema versioning") explicitly anticipates a `schema_version` field per record — v1.18.6's session schema_version: 2 establishes the discipline that ADR 0005's events.jsonl pattern needs
- `ppxai/engine/file_preprocessing.py:264` — image_url block producer (the entanglement point)
- `ppxai/engine/multimodal_ops.py:91-199` — context-attachment scanner (the read-side that depends on the entanglement)
- `ppxai/engine/session.py:286-389` — session serialize/deserialize (the persistence layer that *writes* the entanglement back)
- `ppxai/engine/uploaded_file.py` — precedent for engine-internal block types that get flattened at the boundary (R5, v1.17.6)
- `ppxai/web/app.js:1094, 3598` + `vscode-extension/src/{appState.ts:83, httpClient.ts:147}` — client-side mirrors

## Context

ppxai's multimodal content goes through a single shared shape: an
OpenAI-style content list of `{"type": ..., ...}` blocks. The shape
serves four very different consumers:

1. **Producers** (`/attach` command, server `/chat` route, `file_preprocessing._preprocess_image`)
   build the blocks from raw file bytes plus model+provider context.
2. **Persistence** (`session.py::Session._rewrite_content_for_serialize`
   / `_for_deserialize`) round-trips the blocks through
   `~/.ppxai/sessions/<id>.json` + `~/.ppxai/sessions/<id>/uploads/`.
3. **Engine-internal readers** (`multimodal_ops.py::scan_attachments`,
   `Message.text_content()`, `attach.py::_collect_context_attachments`)
   walk the list to maintain ppxai bookkeeping (the badge counts, the
   AppState `context_attachments` DTO, the `[Image: name]` placeholders
   in logs).
4. **Wire emitters** (`base.BaseProvider._convert_messages`,
   `gemini._content_to_gemini_parts`, `openai_native._convert_messages_for_responses`)
   serialize to provider-specific HTTP payloads.

To keep all four happy, the producers stuff **engine-internal
bookkeeping inside provider wire-format blocks**. The image producer at
`file_preprocessing.py:264-272` emits:

```python
{
    "type": "image_url",
    "name": name,                        # ← ppxai bookkeeping
    "image_url": {"url": "data:..."},
    "file_id": "sha256:...",             # ← ppxai bookkeeping
}
```

The OpenAI Chat Completions spec only allows `{"type", "image_url"}` at
the block level (and `{"url", "detail"}` inside `image_url`).
**`name` and `file_id` are non-spec.** Real OpenAI silently ignores
them; strict OpenAI-compatible endpoints reject the whole request.

### How we got here

R5 (v1.17.6) introduced `uploaded_file` as a first-class
engine-internal block type AND the `flatten_uploaded_file_blocks`
helper that converts it to a legacy text marker before sending. That
established the right pattern: **distinct internal block types get
flattened at the wire boundary.** Image blocks predate R5; they reused
the spec-compliant `image_url` type but bolted ppxai metadata onto it
in-place rather than declaring a separate internal type. The R5
infrastructure for boundary translation already exists; it just doesn't
cover this case.

### Why it bites now

Three concurrent pressures surfaced the entanglement on 2026-05-14:

1. **A user attached a screenshot to gpt-5.5 on the corporate
   `codeai.trad.int` OpenAI-compat endpoint.** The endpoint's strict
   validator returned `"Invalid chat format. Unexpected keys in a
   message content image dict."` The attachment was silently
   dropped — the model never saw it.
2. **ADR 0004's v1 gateway (`POST /v1/oneshot`) is the supported
   external surface for ppxai-sre.** Future ppxai-sre agents will
   forward through gateways that follow the same strict-validator
   pattern (NIM, Azure OpenAI Service, internal corporate proxies).
   Without a clean wire-format discipline, every such integration is
   one strict validator away from a silent multimodal failure.
3. **ADR 0005's `events.jsonl` inspection triplet captures
   provider-bound payloads.** When debugging a "why did the model not
   see my screenshot?" question, an operator inspecting the JSONL
   benefits from seeing wire-clean blocks — not blocks polluted with
   ppxai-internal `file_id` strings that look load-bearing but
   aren't.

### What's tangled, in scope

A `grep -rn '"name":\|"file_id":'` across `ppxai/engine/`:

| File | Sites | Role |
|---|---|---|
| `engine/file_preprocessing.py:266,272` | 2 | Image producer — adds `name`, `file_id` to image_url blocks |
| `engine/session.py:286-343 (serialize), 345-389 (deserialize)` | ~15 | Persistence — reads `block.get("name")`, `block.get("file_id")`; writes them back on serialize |
| `engine/multimodal_ops.py:91-199` | 8 | Context-attachment scanner — reads `block.get("name")`, `block.get("file_id")` to build the `context_attachments` AppState DTO |
| `engine/types.py:243-247` | 2 | `Message.text_content()` reads `block.get("name")` for `[Image: name]` placeholder |
| `commands/attach.py:741` | 1 | `_collect_context_attachments` reads `block.get("name")` |
| `engine/providers/openai_compat.py` | 0 | Sends blocks as-is via base.py — ENTANGLEMENT IS WHAT BREAKS HERE |
| `engine/providers/gemini.py:528-543` | 0 | Walks `image_url` blocks, ignores `name`/`file_id` (Gemini converts shape entirely) — accidentally robust |
| `engine/providers/openai_native.py:740,749` | 0 | Calls `flatten_uploaded_file_blocks` then sends — same entanglement reaches the wire |
| `web/app.js:1094, 3598` + `vscode-extension/src/{appState.ts, chatPanel.ts, httpClient.ts}` | ~10 | **Already read from `context_attachments[]` projection, NOT from message content blocks** |

The last row is the architecturally important one: **the JS/TS
clients have already been built against a separate projection
(`context_attachments`).** They never read `image_url.name` or
`image_url.file_id` directly. That projection is exactly the right
shape — the refactor needs to make the Python side use the same
projection internally rather than keeping a duplicate copy of the
metadata inside content blocks.

## Decision

**Adopt a three-layer schema split for multimodal message content.** The
same conceptual data lives in three explicit forms with explicit
boundaries between them:

```
┌─────────────────────────────────────────────────────────────────┐
│  ENGINE-INTERNAL (rich, ppxai-owned)                            │
│                                                                  │
│  Message.content     : List[ContentBlock]   ← spec-clean blocks │
│  Message.attachments : List[AttachmentRef]  ← ppxai bookkeeping │
└─────────────────────────────────────────────────────────────────┘
                              │
                              │ (1) wire emission via _convert_messages
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  WIRE (provider-spec, lossy on internal metadata)               │
│                                                                  │
│  [{"type":"image_url","image_url":{"url":...}}, {"type":"text"...}]
│                                                                  │
│  No name, no file_id, no internal types.                        │
└─────────────────────────────────────────────────────────────────┘

                              ▲
                              │ (2) projection via scan_attachments
                              │
┌─────────────────────────────────────────────────────────────────┐
│  CLIENT-FACING (DTO, cross-language stable schema)              │
│                                                                  │
│  AppState.context_attachments : List[AttachmentDTO]             │
│  {name, kind, media_type, turn_index, file_id}                  │
└─────────────────────────────────────────────────────────────────┘
```

Each layer has a single purpose and clean conversion to the others.

### Layer 1 — Engine-internal: split content from metadata

**Add a sibling field to `Message`:**

```python
@dataclass
class AttachmentRef:
    """Per-attachment metadata living alongside Message.content."""
    block_index: int        # which content block this annotates
    name: str               # canonical filename
    file_id: str            # SessionFileStore identifier ("" if not persisted)
    media_type: str         # canonical MIME

@dataclass
class Message:
    role: str
    content: MessageContent                          # SPEC-CLEAN blocks only
    attachments: List[AttachmentRef] = field(default_factory=list)
    tool_calls: Optional[List[Dict[str, Any]]] = None
    tool_call_id: Optional[str] = None
```

The `block_index` field is the join key — given `attachments[i]`, the
block it describes is `content[attachments[i].block_index]`. This
preserves ordering across content+metadata without forcing ppxai
metadata into the spec block.

**Image producer simplifies to:**

```python
block = {
    "type": "image_url",
    "image_url": {"url": f"data:{canonical_mt};base64,{b64}"},
}
ref = AttachmentRef(
    block_index=...,        # caller fills in when assembling the message
    name=name,
    file_id=file_id,
    media_type=canonical_mt,
)
return PreprocessResult(parts=[block], attachment_refs=[ref], ...)
```

`build_multimodal_content` already knows the final block ordering, so
it's the natural place to assign `block_index`.

### Layer 2 — Wire: spec-clean by construction

The producer emits spec-clean blocks. **No sanitizer needed** — and none
shipped. (An earlier draft considered a `sanitize_content_blocks_for_wire`
stopgap; it was *not* taken — the producer-side fix went in directly, so
there is nothing to drop. See Status.)

`flatten_uploaded_file_blocks` (R5) keeps doing its job for the
`uploaded_file` engine-internal block type.

`base.BaseProvider._convert_messages` becomes a one-liner: flatten
uploaded_file blocks, return `{role, content, tool_calls, tool_call_id}`.

### Layer 3 — Client-facing: AttachmentDTO is the canonical projection

`multimodal_ops.scan_attachments` already produces this DTO and
publishes it to AppState. Keep that contract — but **change its
input** from "walk content blocks looking for sentinel keys" to "walk
`message.attachments`." That's a one-loop simplification, removes
duplicate dedup logic, and removes the legacy-block-shape fallback
branches.

Cross-language schema lives in `engine/app_state_schema.json` already.
JS+TS mirrors at `web/shared/app-state.js` and
`vscode-extension/src/appState.ts` already type the DTO. **Zero
client-side change.** That's the architectural payoff: the clients
have ALREADY been built against the right abstraction; we're just
making the Python side honor it.

### Persistence (session.py)

Session JSON serializes `Message.content` AND `Message.attachments`
side-by-side. The serialize/deserialize path:

- **Serialize**: walk `attachments` to find `image_url` blocks needing
  bytes-to-file_id rewrite. Store the rewritten URL in
  `content[i]["image_url"]["url"]` (`file://uploads/<id>/<name>`).
  Update `attachments[i].file_id` from the store. Write the message
  with both fields populated.
- **Deserialize**: read `attachments`, look up bytes by `file_id`,
  rewrite `content[i]["image_url"]["url"]` back to a data URI.
- **Backward compat**: when loading a pre-v1.18.6 (v1) session, detect
  the legacy "name/file_id inside image_url block" shape, extract them
  into a synthesized `attachments` list, and strip them from the
  block. One-shot migration on read; no on-disk format flag needed.

### Validator chain at the wire boundary (defense in depth)

Even with spec-clean producers, schema drift over time is inevitable.
Add a **wire-payload validator** that runs in dev/test builds (skipped
in production for performance) and asserts:

- Every block matches `_WIRE_ALLOWED_BLOCK_KEYS[block["type"]]`
- No `image_url` block has `name` or `file_id` keys
- No engine-internal types (`uploaded_file`, hypothetical future
  internal types) reach the wire

Implemented as a 30-line pure-function check called from
`_convert_messages` under `if __debug__`. Test suite asserts the
validator catches each known violation.

This validator is what `sanitize_content_blocks_for_wire` was — but
inverted from "silently fix" to "loudly fail in tests." Production
runs without it because the producers are now correct by
construction.

## Migration plan

All 4 phases land on `bugfix/v1.18.6` as separate commits. Each commit
ships in a green state — no half-done intermediate state. If a phase
surfaces a problem during review the preceding phases stay clean and
mergeable.

### Phase 1 — Add `Message.attachments` field (additive, non-breaking)

**Goal:** new field exists, populated by producers, consumed by
new code paths. Old code paths still work because the legacy
`name`/`file_id` keys still exist inside content blocks.

Steps:
1. Add `AttachmentRef` dataclass to `engine/types.py`
2. Add `attachments: List[AttachmentRef]` field to `Message` (default empty)
3. Update `build_multimodal_content` (`commands/attach.py`) to populate `attachments` alongside content
4. Update producers in `file_preprocessing.py` to RETURN both block + ref tuple
5. Add `Message.attachments` to session JSON serialize/deserialize
6. Tests: round-trip Message with attachments through session save/load; assert ref ordering matches block ordering

**No removals yet.** Old code keeps reading `block.get("name")` etc. —
they get the same values they got before. Sentinel test enforces:
"every content block with a name/file_id key has a matching entry in
`attachments`."

### Phase 2 — Switch readers to `attachments`

Convert all 5 read sites:
- `multimodal_ops.scan_attachments` → walk `message.attachments`
- `Message.text_content()` → look up name from `self.attachments`
- `commands/attach.py::_collect_context_attachments` → walk `message.attachments`
- `session.py::_rewrite_content_for_serialize` → walk `attachments` for known image refs
- `session.py::_rewrite_content_for_deserialize` → write into `attachments`, not block

Sentinel tests for each: same input shape, same output. Fixtures from
the wire-validator sentinels (Step 6, `assert_wire_blocks_clean`) serve
as regression baselines.

### Phase 3 — Remove non-spec keys from producers

- Drop `name` and `file_id` from `file_preprocessing.py:264-272`
- Drop the corresponding writes in `session.py::_rewrite_content_for_serialize`
- Add the wire-format validator (`__debug__`-gated) — asserts every
  block matches `_WIRE_ALLOWED_BLOCK_KEYS[block["type"]]`, loudly fails
  in tests instead of silently fixing payloads at runtime

Sentinel test (will live forever):

```python
def test_image_url_blocks_are_spec_clean():
    """No image_url block emitted by ppxai contains non-spec keys."""
    msg = Message(role="user", content=[{
        "type": "image_url",
        "image_url": {"url": "data:image/png;base64,iVBORw0..."},
    }], attachments=[AttachmentRef(0, "img.png", "sha256:x", "image/png")])
    api = OpenAICompatibleProvider(...)._convert_messages([msg])
    block = api[0]["content"][0]
    assert set(block.keys()) == {"type", "image_url"}
    assert set(block["image_url"].keys()).issubset({"url", "detail"})
```

### Phase 4 — Backward-compat session loader

When loading a session file written by pre-v1.18.6 (v1), the
deserialize path detects the legacy shape (`block["name"]` /
`block["file_id"]` populated, `message["attachments"]` absent) and
reconstructs an `attachments` list from those keys. One-shot migration
on first load; subsequent saves use the new shape.

Test fixture: a v1.18.4 (v1) session JSON checked into `tests/fixtures/`
that deserializes correctly under v1.18.6+, with `attachments`
populated and content blocks stripped of non-spec keys.

## Migration plan revision (2026-05-15)

**Context for the revision:** Phases 1 + 2 landed as planned (commits
`b07bd0fa`, `fb46ee32`, `e91c71aa`) — additive `Message.attachments`
field, populated at producer + deserialize sites, with three reader
sites switched to walk it via the shared `Message.resolve_attachment`
helper. Phase 3 dependency analysis surfaced an architectural
conclusion the original ADR sketch had missed: **Phase 3 cannot ship
cleanly as a standalone commit.** The 3 candidate Phase 3a strategies
each had a real architectural cost:

- **Wire-boundary strip** (`sanitize_content_blocks_for_wire` helper
  in `_convert_messages`) — closes the strict-endpoint user-facing
  bug TODAY but introduces a permanent "wire sees a different shape
  than engine" contract. Fractures the single-source-of-truth invariant
  for `Message.content`. Encourages future engine-internal pollution
  ("just throw it in the block, the strip handles it"). The strip
  exists because we didn't fix the schema, not because the schema
  needs the strip. **Pollution-tolerant architecture — rejected.**

- **Producer-side cleanup via `(parts, refs)` tuple return** — touches
  the public `EngineClientProtocol.chat()` surface, ripples into mocks
  / fakes / integration tests, and re-splits the "Message.attachments
  populated" invariant that Phase 1 unified (producer-side via explicit
  refs, deserialize-side still via `extract_attachment_refs`). Then
  Phase 4's schema_v2 work would have to re-integrate the producer
  pipeline anyway. **Two passes through the same surface — rejected.**

- **Skip Phase 3a, fold producer cleanup into Phase 4** — accepts
  that the strict-endpoint bug stays open for ~1 release cycle.
  Workaround already in place (gpt-5.4 family registry fix, commit
  `e10e4847`, plus cross-client UX warning, commit `2887194a`,
  surface the silent-drop as a structured warning before the API
  rejection happens). **Coherent single-pass refactor — accepted.**

The original ADR ordering ("Phase 3 removes non-spec keys; Phase 4
adds backward-compat loader") only works if Phase 3's producer
cleanup can land independently. Dependency analysis showed it can't:

```
Phase 3 producer cleanup needs ──► AttachmentRef populated WITHOUT
                                    relying on in-block keys
                                    │
                                    ▼
                              Either Phase 4 (session JSON carries
                              attachments separately, producer
                              populates Message.attachments at
                              construction)
                              OR a producer-pipeline tuple-return
                              refactor (rejected above)
```

The two operations — "stop emitting in-block keys" and "switch the
on-disk schema to carry attachments separately" — are structurally
ONE refactor:

- The producer (`file_preprocessing._preprocess_image`) writes
  in-block keys today because that's how `extract_attachment_refs`
  derives `Message.attachments`. Stop one without the other and the
  derive breaks.
- The serialize path (`session._rewrite_content_for_serialize`)
  writes in-block keys back into the on-disk JSON because
  `_deserialize_message` needs them to re-derive `Message.attachments`
  on load. Stop one without the other and session restore breaks.

So the original Phase 3 (drop in-block keys) and original Phase 4
(schema_v2 + migration) collapse into a single Phase 3+4 commit. The
revised plan below replaces the original Phase 3 + Phase 4 sections.

### Revised Phase 3+4 — Producer-pipeline refactor + session schema_version: 2

**Single coherent change.** Producer stops emitting in-block keys at
the same moment session schema_v2 lands so the metadata flow stays
consistent end-to-end:

```
PRODUCER: file_preprocessing._preprocess_image returns (block, ref)
          where block is spec-clean and ref carries name+file_id.
            ↓
ASSEMBLY: build_multimodal_content threads (parts, refs) through
          the producer pipeline; EngineClient.chat receives both
          and constructs Message(content=parts, attachments=refs).
            ↓
WIRE:     BaseProvider._convert_messages walks Message.content as-is.
          Spec-clean by construction — no strip needed.
          Wire validator (__debug__-gated) asserts no non-spec keys
          ever reach a provider; any future producer regression
          fails LOUD in tests.
            ↓
PERSIST:  session JSON carries `schema_version: 2` and persists
          Message.attachments alongside content. _serialize_message
          writes content (spec-clean) + attachments (typed list).
          _deserialize_message reads both directly — no in-block-key
          re-derivation needed for v2 sessions.
            ↓
LEGACY:   v1 session loader detects absent schema_version field +
          in-block name/file_id keys, reconstructs attachments via
          extract_attachment_refs (existing helper), strips the
          in-block keys from content, marks the message for re-save
          in v2 shape. One-shot migration on first load.
```

#### Implementation steps

Each step ships in a green state. CI + targeted test suites green
before moving to the next.

1. **Producer return-shape change.** `_preprocess_image` returns
   `(block, AttachmentRef)` instead of jamming metadata into the
   block. `PreprocessResult` already carries `name` + `file_id` as
   dataclass fields — the producer just stops duplicating them
   inside the content block.

2. **Assembly pipeline plumbing.** `build_multimodal_content` returns
   `(parts, attachment_refs)` instead of just `parts`. 3 callers
   update to unpack the tuple:
   - `commands/attach.py` callers (Rich TUI, Textual TUI)
   - `tui/app.py:876`
   - `rich/main.py:535`
   The server route (`server/routes/chat.py::_build_chat_payload`)
   already returns a tuple post-Phase-1 (the UX warning work made it
   `(payload, warnings)`); extend it to `(payload, warnings, refs)`.

3. **EngineClient.chat receives refs explicitly.** Two options:
   - (a) New keyword arg `attachment_refs: Optional[List[AttachmentRef]] = None`
     on `chat()` — backwards-compatible default; old callers fall
     through to today's `extract_attachment_refs` derivation.
   - (b) New method `chat_with_attachments(content, refs)` — the new
     primary path; `chat(message)` becomes a thin shim that derives
     refs from in-block keys (legacy) and forwards.
   **Pick (a) — the kwarg.** Smaller protocol surface, avoids a
   second method that has to be kept in sync.

4. **Session schema_version: 2.** Top-level field in session JSON.
   `_serialize_message` writes `attachments` field on every message
   that has them. `_deserialize_message` reads `schema_version` from
   the parent dict and routes to v2 vs v1 paths.

5. **Legacy v1 loader.** When `schema_version` is absent or `1`,
   for each message:
   - Run `extract_attachment_refs(content)` to synthesize attachments
     from in-block keys (existing helper, unchanged)
   - Strip `name` + `file_id` keys from content blocks (one-shot
     in-place mutation during load)
   - Mark the session as "needs re-save in v2 shape" (a transient
     flag, NOT persisted) so the next save writes the migrated
     shape
   On v2 sessions: read `attachments` from JSON directly, no
   re-derivation, content blocks already spec-clean.

6. **Wire validator (`__debug__`-gated).** `assert_wire_blocks_clean`
   helper in `engine/uploaded_file.py` (joins the existing
   `flatten_uploaded_file_blocks` and `extract_attachment_refs`
   helpers — same module, same "content-block hygiene" theme).
   Called from `BaseProvider._convert_messages` after flatten.
   Uses `assert` (not `raise`) so production builds with `python -O`
   strip the check; tests + dev builds get the loud failure.

7. **Drop in-block keys from producer.** `file_preprocessing.py`
   line 264-272 emits the spec-clean `{"type": "image_url",
   "image_url": {"url": ...}}` shape only. The corresponding writes
   in `session._rewrite_content_for_serialize` (lines 339-340,
   349-350) also drop — the function still rewrites data URIs to
   `file://uploads/...` references but doesn't re-populate name/file_id
   inside the block.

#### Dependency graph

```
Step 1 (producer return shape) ──► Step 2 (assembly tuple)
                                    │
                                    ├──► Step 3 (chat kwarg)
                                    │
                                    └──► Step 7 (drop in-block keys)
                                                 ↑
Step 4 (schema_v2) ────────────────► Step 7 ─────┘
        │
        └──► Step 5 (legacy loader)

Step 6 (wire validator) ──► independent; can land first as a
                              "guard against the bug we're about to fix"
                              sentinel. Tests pass today because the
                              strip happens at write time before the
                              validator runs.
```

**Recommended commit order:**
1. Step 6 (wire validator) — defensive sentinel, ships green
2. Steps 1+2+3 (producer + pipeline + chat kwarg) — single commit,
   all callers updated atomically; legacy `extract_attachment_refs`
   path still works for tests not using the new pipeline
3. Step 4 (schema_v2 + serialize/deserialize updates)
4. Step 5 (legacy loader)
5. Step 7 (drop in-block keys + producer cleanup) — last because all
   readers must already be migrated AND session-restore must already
   work via schema_v2 OR the legacy loader

Total estimated effort: 3-4 hours focused work, splittable across
multiple sessions if Phase 4-style risk on Step 4-5 warrants pausing
between commits.

#### Deliverables checklist

> **Completed — all steps shipped in v1.18.6** (11-commit arc ending
> `21dd226d`, merged to master). Boxes ticked 2026-06-15 to reflect
> shipped reality (the plan was executed but the checklist was never
> updated in place). Status of this ADR is unchanged (Accepted).

- [x] Step 6: `assert_wire_blocks_clean` helper in
  `engine/uploaded_file.py` + 6-8 sentinel cases
- [x] Step 6: `BaseProvider._convert_messages` calls the validator
  under `__debug__`
- [x] Steps 1-3: `_preprocess_image` returns tuple,
  `build_multimodal_content` returns tuple, `EngineClient.chat`
  takes optional `attachment_refs` kwarg
- [x] Steps 1-3: 3 TUI/server call sites updated atomically
- [x] Steps 1-3: sentinel test pinning that producer-emitted blocks
  are spec-clean even before the wire validator runs
- [x] Step 4: `schema_version: 2` field in session JSON top level
- [x] Step 4: `_serialize_message` persists `attachments` separately
- [x] Step 4: `_deserialize_message` reads `attachments` directly
  on v2 sessions
- [x] Step 5: legacy v1 loader migration path with `extract_attachment_refs`
  + in-block-key strip + transient "needs re-save" flag
- [x] Step 5: permanent regression fixture from a real v1.18.x
  session (use `~/.ppxai/sessions.backup.20260514-161938-before-content-block-refactor/`
  as the source — checked-in fixture in `tests/fixtures/sessions/v1/`)
- [x] Step 5: round-trip test: load v1 fixture → assert in-memory
  shape correct → save → assert on-disk JSON now in v2 shape
- [x] Step 7: producer drops in-block keys
- [x] Step 7: serialize stops writing in-block keys back
- [x] Step 7: full ppxai test suite green (the moment the wire
  validator's __debug__ assertions and the round-trip tests both
  pass, the refactor is complete)

#### Why this is the right call

- **Single source of truth restored.** `Message.content` is the
  spec-clean wire payload. `Message.attachments` is the engine-internal
  metadata. No place in the codebase needs to ask "which shape am I
  reading?"
- **No permanent strip.** The wire validator catches future
  regressions; it doesn't paper over them.
- **Producer pipeline refactored once, not twice.** The original
  Phase 3a tuple-return change would have been re-touched in Phase 4.
- **Phase 4 is no harder than originally scoped.** Original Phase 4
  was already going to handle session schema migration; combining it
  with producer cleanup adds the producer return-shape change but
  removes the orphan "drop in-block keys but session-restore still
  needs them" intermediate state.

## Strategic rationale (2026-05-15) — v1.18.6 establishes the v1.19.x agent platform foundation

**The original ADR 0006 framed v2 as session schema cleanup driven by
the strict-endpoint user-facing bug. That framing UNDERSELLS the work.**
Re-evaluation through the v1.19.x agent platform lens (per ADR 0003)
shows v2 is load-bearing for the upcoming sub-agent + autonomous-agent
roadmap, not just a bug fix.

### What the agent platform actually persists per run

ADR 0003 §"Proposed architecture" specifies the per-agent-run namespace:

```
~/.ppxai/runs/<run_id>/agent-<n>/   (ADR 0003 / ADR 0005 canonical path)
    ├── meta.json     (task, parent, status, ...)
    ├── events.jsonl  (append-only)
    ├── state.json    (iteration, budget, tools)
    └── transcript.md
```

**Each run carries its own message history.** Sub-agents and autonomous
agents both produce conversations — same `Message` shape, same content
blocks, same potential for image attachments. Whatever schema we use
for `~/.ppxai/sessions/` will be inherited by `runs/<run_id>/agent-<n>/`.
The schema we ship in v1.18.6 IS the schema v1.19.x agents inherit.

### Four agent-platform pressures that strengthen the v2 case

1. **Cross-process readers.** ADR 0003 commits to "agent runs survive
   engine restart." That means an artifact written by ppxai process A
   may be read by:
   - A different ppxai process (after restart)
   - A run-viewer tool (`ppxai agent show <run_id>`)
   - `kubectl exec cat` (per ADR 0005 inspection triplet)
   - Parent-agent observability code in a different EngineClient
   - External operator tooling

   If the persisted shape requires "re-derive `Message.attachments`
   from in-block keys via `extract_attachment_refs`," that derivation
   logic must live in EVERY reader. **v2 schema (self-describing,
   attachments persisted separately) lets readers consume the artifact
   without knowing the producer's derivation rules.** The wire-strip
   alternative does NOT solve this — strip happens at engine→wire,
   doesn't help cross-process disk readers.

2. **Long-lived `events.jsonl` per run.** ADR 0005 §"Open decisions"
   item 2 explicitly says: *"events.jsonl entries should carry a
   schema_version field per record so a consumer reading a long-lived
   file across ppxai upgrades knows what to expect."* If a sub-agent
   writes events spanning an hour and ppxai is upgraded mid-run (the
   autonomous-agent use case explicitly survives restarts), readers
   need to handle multiple schema versions in the same file.

   **The schema_version discipline isn't bug-fix infrastructure — it's
   the foundational primitive for long-lived artifacts.** v1.18.6
   establishes it on `sessions/` so v1.19.x agent runs inherit a
   working pattern, not invent it in haste.

3. **Sub-agent message construction.** ADR 0003 Question D recommends
   D1 (new EngineClient per sub-agent run). Sub-agents construct
   messages programmatically, NOT from user input flowing through
   `build_multimodal_content`. With v2 (Phases 1+2 already shipped):

   ```python
   # Sub-agent code is direct, no producer pipeline indirection:
   sub_engine.chat(
       content=[{"type": "text", "text": task},
                {"type": "image_url", "image_url": {"url": data_uri}}],
       attachment_refs=[AttachmentRef(block_index=1, name="x.png", file_id="...", media_type="image/png")],
   )
   ```

   **Without v2 (wire-strip alternative), sub-agent code must either
   re-emit the messy in-block-keys convention or bypass the producer
   pipeline entirely** — both fracture the architectural story.

4. **ppxai-sre external integrations** (per ADR 0004 v1 gateway + the
   ppxai-sre research note). The v1 gateway is the supported external
   surface; future ppxai-sre agents pass payloads through it. Strict
   OpenAI-compat endpoints (NIM, corporate gateways) are the SAME
   class of consumer that hit the original `Invalid chat format` bug.

   **Wire-strip works for now but is a permanent tax** on every wire
   path; v2 makes wire-clean an INVARIANT, not a runtime check.

### Updated technical reasons for v2 (rewriting the original rationale)

| Reason | Original framing | v1.19.x agent-platform framing | Strength |
|---|---|---|---|
| A. Wire payload spec-clean | Closes strict-endpoint bug | Required for v1 gateway → ppxai-sre integration to be reliable across strict downstreams | **Strong** (was strong, now strategic) |
| B. Message.attachments as source of truth | Architectural cleanliness | Sub-agents construct Message directly without producer pipeline indirection | **Strong** (was medium, now load-bearing) |
| C. Producer cleanup at the producer | Stops engine-internal pollution | Sub-agent message construction is uniform with user-input construction | **Strong** (was weak, now load-bearing) |
| D. Future block types inherit clean pattern | Speculative | Agent runs introduce new persisted artifact types (meta/state/events/transcript) — pattern matters | **Strong** (was speculative, now imminent) |
| E. events.jsonl inspection clarity | Speculative | ADR 0005 EXPLICITLY needs schema_version per record; v2 establishes the discipline on sessions first | **Strong** (was speculative, now precondition) |

All five reasons strengthen under the agent-platform lens.

### Concrete benefit chain

1. **v1.18.6**: `sessions/<id>.json` gets `schema_version: 2`. Migration loader pattern established. Wire validator in place. Producer pipeline cleaned.
2. **v1.19.x Stage 2** (agent run registry): agent runs get `meta.json` / `state.json` / `events.jsonl` with their own `schema_version: 1` (own track) — but the migration loader pattern is already battle-tested from v1.18.6.
3. **v1.19.x Stage 3** (sub-agent spawning): sub-agents construct `Message(content=..., attachments=[...])` directly. Same pattern as parent's session messages. No producer pipeline import in agent code.
4. **ppxai-sre external integration**: v1 gateway promises spec-clean wire payloads invariant of provider strictness.

### Migration policy (per user direction 2026-05-15)

When v1.18.6 loads a v1.18.5-or-earlier session:

- ✅ **Preserve**: text message history (user + assistant + tool turns), tool calls, tool results, session name, model, provider, working_dir, usage stats, costs, session metadata, non-image attachments (PDF/code/Excel `uploaded_file` blocks)
- ❌ **Drop**: image attachments (`image_url` blocks). Replace with text placeholder noting what was lost: `[Image attachment dropped during v1→v2 migration: <name>]`
- 📁 **Old uploads directory** (`~/.ppxai/sessions/<id>/uploads/`) is NOT auto-deleted. Migration prompts the user (next time they open the affected session) whether to keep it for reference or delete it. Default: keep.
- 📝 **Optional future enhancement** (not v1.18.6 hard requirement): the migrated v2 message could carry an `AttachmentRef` whose `file_id` points at the v1 uploads path so the artifact is recoverable through the file_store API. **Decision deferred** — adds complexity for a workflow user explicitly de-prioritized. Revisit if a v1.18.6 user requests it.

This policy is documented in the v1.18.6 release notes as a breaking
change. The `~/.ppxai/sessions.backup.20260514-161938-before-content-block-refactor/`
directory created during this work serves as the reference v1 backup
for both the developer's own data and the test fixture source.

### Why this beats the wire-strip alternative

The wire-strip (`sanitize_content_blocks_for_wire` helper called from
`BaseProvider._convert_messages`) was considered as a smaller v1.18.6
fix:

- ✅ Closes the strict-endpoint user bug today
- ✅ ~80 LoC vs ~700 LoC for full v2
- ❌ **Doesn't solve cross-process disk readers** — strip is engine→wire,
  not disk-write. Agent run viewers still see polluted blocks.
- ❌ **Doesn't establish schema_version discipline** — v1.19.x agent
  runs would have to invent it
- ❌ **Producer pollution stays permanent** — encourages future engine-
  internal metadata to ride inside content blocks because the strip
  "handles it"
- ❌ **Sub-agent message construction stays messy** — sub-agent code
  must know to emit the in-block-keys convention OR import producer
  pipeline OR contribute to drift

**Strategic verdict:** wire-strip is a tactical band-aid for one bug
class. v2 is foundational infrastructure for the next major release.
Same 5 hours of focused work; vastly different long-term return.

## Consequences

### What this enables

- **Strict OpenAI-compat endpoints work natively** (corporate
  gateways, NIM, vLLM with strict validators). ppxai-sre's v1
  gateway becomes safe to point at any compliant LLM endpoint.
- **`events.jsonl` payloads are wire-clean** (per ADR 0005). An
  operator inspecting "what did we send to the provider?" sees the
  exact bytes, not ppxai-polluted blocks.
- **Persistence schema is principled.** Storing `attachments` as a
  sibling field documents that ppxai bookkeeping is distinct from
  wire payload, instead of hiding metadata inside a payload field.
- **JS/TS clients need zero change.** They already consume the
  AttachmentDTO via AppState. The Python refactor just makes the
  internal flow match what the clients have always assumed.
- **Future block types are easier.** When v1.20.x adds (say) an
  audio block, the schema choice "internal type that gets flattened
  vs. spec-compliant from the start" has a clear precedent.

### What this requires

- **Phase 1 + Phase 2 are an additive 2-week refactor.** Phase 3 and
  Phase 4 land together when all readers have been switched.
- **`Message` schema change.** Adding a field is non-breaking but
  requires care in equality checks, hash, and any JSON dumpers that
  use `dataclasses.asdict`. Test coverage must include
  `dataclasses.asdict(msg)` round-trip and pickle (used by
  conversation-export tests).
- **Session JSON schema bump.** A `schema_version: 2` field at
  the top of session JSON files, **shipped in v1.18.6**. The loader
  checks the version and routes to the legacy-migration path if absent
  or `1`. (This section was written when the work targeted v1.19.x;
  it landed in v1.18.6 — see the checklist note above.)
- **Sentinel test discipline.** Two new permanent sentinels:
  - `test_image_url_blocks_are_spec_clean` (Phase 3)
  - `test_legacy_session_loads_correctly` (Phase 4)

### Risks

| Risk | Mitigation |
|---|---|
| `Message.attachments` and `Message.content` get out of sync (block deleted but ref remains, etc.) | Validator helper `Message.validate_attachments()` runs in `__debug__` builds; called after every mutation |
| Legacy session files with weird shapes (manual edits, third-party tools) crash the migration | Migration wraps in try/except, falls back to legacy in-block reads with a warning logged once per session |
| Phase 2 reader switch missed a site | Whole-repo grep for `block.get("name")` / `block.get("file_id")` in CI; sentinel test with a fully-populated multimodal Message asserts every projection layer sees the same name/file_id |
| ppxai-sre or other downstream consumers depend on the legacy shape | Search ppxai-sre repo for content-block reads before Phase 3; if any exist, bump v1 gateway schema_version and document the change in `docs/api-gateway.md` |
| VSCode extension's TypeScript types drift | Run `python scripts/regen_appstate_types.py` (existing script per `ppxai/engine/app_state_schema.json`) after Phase 1; CI sentinel asserts TS types match |

### What this is NOT

- **Not a wire-protocol change.** Real OpenAI keeps accepting the same
  payload it always has (it ignored the extra keys anyway). The change
  is internal cleanup.
- **Not a session-format break.** The v1→v2 session boundary is
  **v1.18.5 → v1.18.6**: v1.18.6+ readers handle old v1 (≤v1.18.5)
  files via the migration path; pre-v1.18.6 readers WILL fail on v2
  files (forward compat is one-way only). Documented in
  `docs/release-notes-v1.18.6.md` (this bullet originally said
  v1.19.x, before the work was pulled forward into v1.18.6).
- **Not an architectural pattern other than "boundary types matter."**
  The Triplet (ADR 0005), the AppState schema (ADR 0001-style work),
  and now this content-block split are all the same instinct: when
  one shape serves multiple consumers with different validity rules,
  give each consumer its own type and translate at the boundary.

## Why now

Three forcing functions overlap on 2026-05-14:

1. **The 2026-05-14 user incident** (gpt-5.5 silently dropped a
   screenshot attachment) is the visible bug. It will recur every
   time someone points ppxai at a strict OpenAI-compat endpoint
   until producers are clean.
2. **ADR 0004's v1 gateway expansion for ppxai-sre** is queued for
   v1.19.x. Pointing the gateway at downstream LLMs without first
   establishing wire-format discipline guarantees one of those
   downstream endpoints will be strict and the issue resurfaces in
   production traffic.
3. **The R5 precedent (`flatten_uploaded_file_blocks`) shows the
   pattern works.** This ADR codifies the same boundary-translation
   discipline for image_url blocks, completing the pattern.

Capturing the decision now means later agent-platform work can implement
mechanically against a clear plan rather than relitigating shape choices
each phase. The v1.18.6 producer-side fix ships the clean shape directly —
no stopgap, no shortcut taken as the permanent answer (see Status).

## Scope guards

- Not a `Message` rewrite. Adding one field (`attachments`), keeping the others.
- Not a content-block-type expansion. The block types stay
  (`text`, `image_url`, `uploaded_file`, `input_file`, `file`). Only
  the *contents* of `image_url` blocks change.
- Not a provider rewrite. `gemini.py` already correctly ignores
  non-spec keys (it uses its own shape entirely); `openai_native.py`
  inherits from `base.py` which inherits the cleanup automatically.
- Not a JS/TS client change. The clients have already been on the
  right side of this since AppState DTOs landed in v1.17.x.
