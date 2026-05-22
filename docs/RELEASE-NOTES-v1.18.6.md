# Release Notes — v1.18.6

> **Scope:** A foundation release that decouples engine-internal
> attachment metadata from the OpenAI wire format, establishes the
> plug-n-play artifact framework that v1.19.x agent platform work will
> consume, and ships a one-way v1 → v2 session migration with a
> documented breaking change for legacy multimodal sessions.
>
> **Theme 1 — ADR 0006 content-block schema separation.** The
> historical shape `{"type": "image_url", "name": "shot.png",
> "file_id": "abc123", "image_url": {"url": "..."}}` jammed
> engine-internal bookkeeping (`name`, `file_id`) into the OpenAI
> spec block. Strict OpenAI-compat endpoints (corporate gateways,
> NIM, vLLM with strict validators) reject these requests with
> `Invalid chat format. Unexpected keys in a message content image
> dict.` v1.18.6 reorganizes the data: image_url blocks now carry
> ONLY the spec keys (`{type, image_url}`); engine-internal metadata
> lives on `Message.attachments` as typed
> [MarshallableArtifact](../ppxai/engine/types.py) refs (`ImageAttachmentRef`,
> `PdfAttachmentRef`, `OfficeAttachmentRef`, `TextAttachmentRef`).
> Session JSON gains `schema_version: 2` with a per-message
> `attachments` array round-tripped via the new
> [ArtifactRegistry](../ppxai/engine/artifact_registry.py)
> kind-discriminated dispatch.
>
> **Theme 2 — ArtifactRegistry + ArtifactProjector plug-n-play
> framework.** Two architectural primitives mirror the existing
> `rendering/base.py::Renderer` per-subclass `_registry` model.
> `ArtifactRegistry.register("image")` decorates the dataclass for
> kind-discriminated serialize/deserialize.
> `<Projector>.register("image")` decorates a per-consumer projection
> handler. Three concrete consumers ship in v1.18.6:
> `ContextAttachmentProjector` (badge DTO), `TextMarkerProjector`
> (token-counted text placeholder), `MessageBoxProjector` (TUI chip
> label). Adding a v1.19.x sub-agent artifact kind = decorate one new
> dataclass + one handler per consumer. Zero reader edits.
>
> **Theme 3 — v1 → v2 session migration with backup-preservation.**
> Sessions saved by ppxai ≤ 1.18.5 are migrated transparently on
> first load by a 1.18.6 build: text content + tool_calls + metadata
> preserved verbatim; image / uploaded_file blocks dropped with text
> placeholders pointing at a preserved `<name>.v1.backup/` sibling
> folder. **Breaking change:** users with multimodal v1 sessions lose
> the in-conversation image rendering on those sessions; original
> bytes survive in the backup folder for forensic recovery. Pure-text
> v1 sessions migrate naturally on next save with no backup needed.
>
> **Side themes.** Default model `gpt-5.4-mini` registry gap fixed —
> previously routed images to text-placeholder fallback because
> `supports_vision()` returned False (no profile entry). Gemini 3.1
> Flash Lite preview → GA migration (Google retirement deadline
> 2026-05-25). VSCode extension gains its proper gallery icon
> (no more Lego-brick placeholder). build-install skill +
> Windows `code.cmd` shim path correction.
>
> **Tests:** 3695 pass, 2 skipped (whole-suite count on macOS, run
> 2026-05-15); zero regressions across the 17 ADR-0006-affected
> reader/producer suites. The 2 macOS skips are `tests/test_gemini_extras.py`
> (conditional on `google-genai` install). Windows runs additionally
> skip the 11 `@_unix_only`-marked tests in `tests/test_server_state.py`
> (TestKillPreviewBackend + TestKillPreviewBackendDrainTask). New ADR
> 0006 sentinel suites:
> 39 cases in `test_artifact_registry.py`, 30 in
> `test_artifact_projector.py`, 9 in `test_session_schema_v2.py`,
> 9 in `test_v1_session_migration.py`, 20 in
> `test_wire_block_validator.py`. Permanent regression fixture at
> `tests/fixtures/sessions/v1_with_image/`.

## Summary

v1.18.6 ships the architectural foundation that v1.19.x agent platform
work (per [ADR 0003](decisions/0003-agent-platform-architecture.md))
inherits or extends. Every infrastructure primitive ADR 0003 needs —
artifact identity, persistence, cross-process readers, sub-agent
message construction — derives from what this release establishes.
Strategic rationale captured in
[ADR 0006 strategic-rationale section](decisions/0006-content-block-schema-separation.md#strategic-rationale).

The breaking change is contained: only multimodal v1 sessions lose
their in-conversation image rendering, and the original bytes survive
in the preserved backup folder. Pure-text sessions migrate
transparently. Producers / consumers built against v1.18.6 emit
spec-clean wire payloads — no more "unexpected keys in image dict"
rejections from strict OpenAI-compat endpoints.

## ADR 0006: Content-block schema separation

### What changed on the wire

**Before (v1.18.5 and earlier):**
```json
{
  "type": "image_url",
  "name": "shot.png",
  "file_id": "abc123",
  "image_url": {"url": "data:image/png;base64,..."}
}
```

**After (v1.18.6+):**
```json
{
  "type": "image_url",
  "image_url": {"url": "data:image/png;base64,..."}
}
```

Engine-internal metadata moves to `Message.attachments`:
```python
Message(
    content=[{"type": "image_url", "image_url": {"url": "..."}}],
    attachments=[
        ImageAttachmentRef(
            block_index=0, name="shot.png",
            file_id="abc123", media_type="image/png",
        ),
    ],
)
```

### What changed on disk

Session JSON gains a top-level `schema_version: 2` and a per-message
`attachments` array:

```json
{
  "schema_version": 2,
  "messages": [
    {
      "role": "user",
      "content": [{"type": "image_url", "image_url": {"url": "..."}}],
      "attachments": [
        {
          "kind": "image",
          "_schema_version": 1,
          "block_index": 0,
          "name": "shot.png",
          "file_id": "abc123",
          "media_type": "image/png"
        }
      ]
    }
  ]
}
```

The `file://uploads/<file_id>/<name>` URL convention round-trips
file-store metadata for image_url blocks; `Message.attachments`
round-trips heterogeneous artifact kinds via
`ArtifactRegistry.deserialize`.

### Plug-n-play architecture

Two registries form the framework. Both mirror the existing
`rendering/base.py::Renderer` per-subclass `_registry` model exactly.

**`ArtifactRegistry`** — kind-discriminated class discovery for
serialize / deserialize:
```python
@ArtifactRegistry.register("image")
@dataclass
class ImageAttachmentRef:
    SCHEMA_VERSION: ClassVar[int] = 1
    block_index: int
    name: str
    file_id: str = ""
    media_type: str = ""
    kind: str = "image"

    def to_dict(self) -> dict: ...

    @classmethod
    def from_dict(cls, data: dict) -> "ImageAttachmentRef": ...

# Cross-process readers consume serialized refs uniformly:
ref = ArtifactRegistry.deserialize({"kind": "image", ...})
```

**`ArtifactProjector`** — per-consumer projection registries.
Each consumer is its own subclass with its own `_registry`:
```python
@ContextAttachmentProjector.register("image")
def _project_image(ref):
    return {"name": ref.name, "kind": "image",
            "media_type": ref.media_type, "file_id": ref.file_id}

# Consumer side:
entry = ContextAttachmentProjector.project(ref)
```

Three concrete consumer projectors ship in v1.18.6:
`ContextAttachmentProjector`, `TextMarkerProjector`,
`MessageBoxProjector`. Per-kind handlers register at engine-import
time via `ppxai/engine/artifact_projections.py`.

**Adding a v1.19.x sub-agent artifact kind:**
1. Define the dataclass + decorate with `@ArtifactRegistry.register("subagent_plan")`
2. Add one handler per consumer in `artifact_projections.py`
3. Done — zero reader edits

**Adding a new consumer projector** (e.g. `WireBlockProjector` for
v1.19.x sub-agent message construction):
1. `class WireBlockProjector(ArtifactProjector): pass`
2. One `@WireBlockProjector.register("kind")` decorator per artifact
3. Consumer code calls `WireBlockProjector.project(ref)`

### Wire validator (defensive sentinel)

`assert_wire_blocks_clean()` runs in `BaseProvider._convert_messages`
in `__debug__` builds. Walks every content block; asserts each block's
keys match the OpenAI spec for its type. Catches producer-side
regressions where an engine-internal key (e.g. `name`, `file_id`)
slips back into a wire block. Production builds (`python -O`) strip
the assertion entirely — zero runtime cost.

## Breaking change: v1 → v2 session migration

### Detection

A session is treated as v1 when its top-level JSON has
`schema_version` absent OR `== 1`.

### Auto-migration on first load

On first load by a 1.18.6+ build, multimodal v1 sessions migrate
transparently:

1. **Backup** — the v1 session folder copies to
   `<sessions_dir>/<name>.v1.backup/` (or `<name>.v1.backup.json`
   for flat sessions). Original bytes preserved untouched. Backup
   folders are excluded from `list_sessions()` so they don't surface
   as duplicate session entries.
2. **Rewrite** — every `image_url` / `uploaded_file` block in
   user messages is replaced with a text placeholder:
   ```
   [v1 migration: image_url 'shot.png' dropped — original bytes
   preserved at <name>.v1.backup/]
   ```
   Text content + tool_calls + metadata + persistence fields all
   pass through unchanged.
3. **Persist** — immediate save() in v2 schema (no wait for next
   save_dirty cycle).
4. **Log** — a single INFO line per migrated session.

Pure-text v1 sessions (no multimodal blocks) skip the backup step
entirely — they migrate to v2 naturally on the next normal save with
no data loss and no backup folder.

### What users lose

Users with multimodal v1 sessions lose the in-conversation image /
PDF rendering on those sessions when loaded by a 1.18.6 build. The
provider can no longer interpret the dropped image; the user sees
the placeholder instead.

### What users keep

- All text content (system prompts, user prompts, assistant responses)
- All tool calls + tool results (preserved byte-identical)
- Session metadata (created_at, provider, model, message_count)
- Persistence fields (working_dir, command_history, tools_enabled)
- Original v1 folder + uploads/ subtree at `<name>.v1.backup/` for
  forensic recovery (delete manually when no longer needed)

### Idempotence + safety

- `schema_version: 2` sessions skip migration entirely (no double-backup)
- Already-existing `<name>.v1.backup/` left in place (never overwritten)
- Loading `<name>.v1.backup` directly is read-only — never re-fires
  the migration (no nested `.v1.backup.v1.backup/` from forensic loads)
- Backup-copy failure aborts migration: in-memory state is still
  loaded normally; on-disk session stays at v1 for next launch retry

### Test coverage

Sentinel suites pin the migration contract:

- `tests/test_v1_session_migration.py` — 9 cases covering backup
  creation, idempotence, list_sessions filtering, read-only backup load
- `tests/fixtures/sessions/v1_with_image/` — permanent regression
  fixture (real v1.18.x-shape session with image attachment, multi-turn)
- `tests/test_session_schema_v2.py` — 9 cases pinning v2 round-trip
  and v1 detection

## Side themes

### gpt-5.4-mini registry gap (the trigger for this release)

**Problem.** The default model `gpt-5.4-mini` had no entry in
`BUILTIN_PROFILES` despite being the project default since v1.17.4.
`supports_vision()` returned False via the conservative default ⇒
screenshot attachments silently routed to the text-placeholder
fallback in `file_preprocessing.py:309-325`. The model never saw the
image.

**Fix** (`e10e4847`). Added `gpt-5.4-mini*` + `gpt-5.4*` glob entries
to `BUILTIN_PROFILES`, cloned from the gpt-5.5/gpt-5.2 shape
(supports_vision=True, tier A). Test parametrize extended to cover
gpt-5.4 family.

This bug is what motivated the ADR 0006 overhaul: it surfaced
exactly how brittle the in-block metadata + silent-fallback
combination was. v1.18.6 closes the loop with proactive UX
warnings + the architectural separation that makes such gaps
visible in the future.

### Gemini 3.1 Flash Lite preview → GA

Google announced retirement of `gemini-3.1-flash-lite-preview` on
2026-05-25. v1.18.6 renames the model identifier to the GA name
`gemini-3.1-flash-lite` across:
- `model_deprecations.py` (replacement targets + recommendation row)
- `ppxai-config.json` + `ppxai-config.example.json`
- `multimodal-api-models-reference.md`
- Test assertions in `test_doctor.py` + `test_model_vision.py`

The wildcard glob in `model_profiles.py` (`gemini-3.1-flash-lite*`)
already covered both names — no change needed there.

### VSCode extension icon

Pre-v1.18.6 extension shipped without a top-level `"icon"` field in
`package.json`, so VS Code's installed-extensions list rendered a
generic Lego-brick placeholder. v1.18.6 wires
`"icon": "resources/icon.png"` to the existing 128×128 RGBA chat-bubble
asset (brand-consistent with the web favicon). Reload Window to see
the icon in the list.

### build-install skill: Windows `code.cmd` resolution

The previous skill assumed `code` on PATH resolves to the CLI shim;
on machines where it points to `Code.exe` (the GUI), `--install-extension`
fails. Fixed in skill commit `114d16f3` to resolve
`$env:LOCALAPPDATA\Programs\Microsoft VS Code\bin\code.cmd` directly.

## Files changed

### New files
- `ppxai/engine/artifact_registry.py` — kind-discriminated class registry
- `ppxai/engine/artifact_projector.py` — per-consumer projection
  registries + 3 concrete subclasses
- `ppxai/engine/artifact_projections.py` — per-kind projection handlers
  (4 kinds × 3 projectors = 12 handlers)
- `tests/test_artifact_registry.py` — 39 cases
- `tests/test_artifact_projector.py` — 30 cases
- `tests/test_session_schema_v2.py` — 9 cases
- `tests/test_v1_session_migration.py` — 9 cases
- `tests/test_wire_block_validator.py` — 20 cases
- `tests/fixtures/sessions/v1_with_image/` — permanent regression fixture

### Modified files
- `ppxai/engine/types.py` — `MarshallableArtifact` Protocol +
  4 typed dataclasses (`ImageAttachmentRef`, `PdfAttachmentRef`,
  `OfficeAttachmentRef`, `TextAttachmentRef`); `Message.attachments`
  field; `Message.text_content` migrated to projector dispatch;
  `_synthesize_block_ref` helper
- `ppxai/engine/session.py` — `schema_version: 2` constant;
  serialize / deserialize via ArtifactRegistry; `_parse_file_uploads_url`
  + `_attachments_from_serialized_content` helpers; v1 → v2 auto-migration
  (`_migrate_v1_to_v2_if_needed`, `_backup_v1_session`,
  `_strip_multimodal_blocks_for_v1_migration`); `list_sessions()`
  filters out `*.v1.backup` entries
- `ppxai/engine/file_preprocessing.py` — producers populate
  `result.attachment_ref`; image producer emits spec-clean
  `image_url` blocks
- `ppxai/engine/multimodal_ops.py` — scanner walks
  `Message.attachments` and dispatches via `ContextAttachmentProjector`;
  `_synthesize_refs_from_content` + `_ref_from_legacy_text_marker`
  bridges; `_block_matches` reworked to look up
  `Message.attachments` by `block_index` for image blocks
- `ppxai/engine/uploaded_file.py` — `assert_wire_blocks_clean` validator
- `ppxai/engine/providers/base.py` — wire validator hooked into
  `_convert_messages`
- `ppxai/engine/client.py` — `chat()` accepts `attachment_refs` kwarg
  passed through from server / TUI
- `ppxai/engine/streaming.py` — `sse_event_generator` plumbs
  `attachment_refs`
- `ppxai/server/routes/chat.py` — `_build_chat_payload` returns
  `(payload, warnings, refs)` 3-tuple; vision warnings emitted as
  `Event(EventType.WARNING, ...)` before chat starts
- `ppxai/commands/attach.py` — `build_multimodal_content` returns
  `(parts, refs)`; `_collect_context_attachments` migrated to projector
- `ppxai/tui/widgets/message_box.py` — `normalize_content_to_text`
  migrated to `TextMarkerProjector`
- `ppxai/rich/main.py` + `ppxai/tui/app.py` + `ppxai/tui/stream_handler.py`
  — thread `attachment_refs` through to `engine.chat()`
- `ppxai/engine/__init__.py` — import `artifact_projections` for
  side-effect registration

## Migration guide

### Users on v1.18.5 or earlier

No action required. On first launch of v1.18.6, ppxai detects v1
sessions automatically:

- **Pure-text sessions** — silent migration on next save. No data
  loss, no backup folder.
- **Multimodal sessions (image / PDF / Office attachments)** —
  auto-migration runs on first load:
  - Original session backed up to `<name>.v1.backup/` (or `.v1.backup.json`
    for flat sessions)
  - Image / PDF / Office blocks replaced with text placeholders
    pointing at the backup folder
  - Session re-saved as v2 (`schema_version: 2`)
  - Single INFO log line per migrated session
- **Backup cleanup** — once you've verified the migrated session
  works, delete `<name>.v1.backup/` manually. ppxai never touches
  these folders after creation.

### Users with custom integrations (provider adapters, exporters)

If you've written code that constructs `Message` objects with raw
`image_url` blocks containing in-block `name` / `file_id` keys: the
new producer pipeline + serializer still tolerate these inputs
(transitional `block.get("name")` fallback survives in
`_rewrite_content_for_serialize`), but the SAVED on-disk JSON will
be spec-clean. Reads from the saved JSON via your code that depended
on `block["name"]` / `block["file_id"]` will see those keys absent.
Switch your reader to walk `Message.attachments` (the v2 source of
truth) or parse the file_id from `block["image_url"]["url"]` (which
is `file://uploads/<file_id>/<name>` after serialize).

### Users with strict OpenAI-compat endpoints

If your gateway / NIM / vLLM was rejecting requests with
`Invalid chat format. Unexpected keys in a message content image dict.`,
v1.18.6 fixes this. The wire payload now matches the OpenAI Chat
Completions spec exactly.

## What's next

v1.18.6 establishes the foundation. v1.19.x will build the agent
platform on top:

- Sub-agents producing typed `MarshallableArtifact` outputs (plan
  documents, tool artifacts, image renderings)
- `events.jsonl` per agent run with the same `schema_version`
  discipline (per [ADR 0005 Inspection Triplet](decisions/0005-inspection-triplet.md))
- `WireBlockProjector` for sub-agent → root-agent message construction
- Cross-process artifact reading by ppxai-sre (per [ADR 0004 v1
  API gateway](decisions/0004-v1-api-gateway.md))

All of these inherit the v1.18.6 framework primitives — no new
dispatch system, no new schema-version discipline, no new
registration model. See
[ADR 0006 strategic-rationale](decisions/0006-content-block-schema-separation.md#strategic-rationale)
for the full chain.

## Acknowledgments

Triggered by the gpt-5.4-mini multimodal incident (2026-05-14). The
investigation surfaced exactly how brittle the in-block metadata +
silent-fallback combination was, and the user chose the architectural
fix (full v2 schema) over the surface fix (just add the model entry).
Both shipped in this release.
