# Release Notes — v1.17.6

## Summary

**R5 — promote uploaded-file attachments to a first-class content-part type.** Non-image attachments (PDFs, Office documents, large CSVs) used to travel as `<uploaded_file>` XML markers embedded inside `{"type": "text"}` content blocks — a design debt tracked since v1.17.4. Every consumer had to regex-parse text to find attachments, and clients rendered the raw XML in chat bubbles. v1.17.6 introduces a dedicated content block:

```json
{
  "type": "uploaded_file",
  "name": "report.pdf",
  "media_type": "application/pdf",
  "file_id": "sha256:abc",
  "summary": "PDF attached. Use read_pdf.",
  "extra": {"pages": "12", "size_kb": "520.3"}
}
```

No new user features. Internal wire-format change, delivered as a staged rollout with a strict byte-identical-LLM-strings invariant.

**2068 tests passing (+65 net from v1.17.5), zero regressions.**

## Why this matters

- **Consumer simplification** — `refresh_context_attachments`, `remove_context_attachment`, and the R10 multimodal-cache predicate now dispatch on `block["type"]` instead of scanning text with regex.
- **Cleaner client rendering** — web and VSCode chat bubbles now show a compact `[Attached: name (media_type)]` badge instead of raw XML.
- **R1/R7 collapse** — future work around attachment identity and removal no longer needs to reconcile three places that emit/parse the same marker.
- **Foundation for v1.18.x** — richer client rendering (real filename badges, inline previews for Office docs) becomes easy now that the attachment metadata lives in a structured shape.

## How it's safe to land

The LLM must see byte-identical strings during the rollout — otherwise model behavior and token counts drift silently. Provider adapters enforce this:

- `base.BaseProvider._convert_messages` (OpenAI, OpenAI-compat, Perplexity, OpenAI-native chat path)
- `gemini.GeminiProvider._content_to_gemini_parts` (Gemini's whole conversion chain)
- `openai_native.OpenAINativeProvider._convert_messages_for_responses` (Codex/Pro models via Responses API)

All three call `flatten_uploaded_file_blocks()` immediately before shaping the API payload. The flatten uses the same `format_uploaded_file_reference()` helper that producers used pre-R5, so the marker string reaching the model is exactly what it was before. An explicit test pins this (`test_byte_identical_to_legacy_producer_output`).

## Backward compatibility

- **Sessions saved by pre-v1.17.6 ppxai continue to load** — consumers recognize both the new structured block AND the legacy text-marker form.
- **Mid-rollout sessions** (some turns emitted by pre-R5, some by post-R5) work transparently; attachments from both shapes surface in the same context-attachment badge strip and are both removable via `/attach remove`.
- Session round-trip preserves every field (`name`, `media_type`, `file_id`, `summary`, `extra`) through JSON save/load.

## Staged rollout (six commits)

| Stage | Commit | Scope |
|-------|--------|-------|
| 1 | `8c626e13` | Schema helpers — `make_uploaded_file_block`, `uploaded_file_block_to_text`, `flatten_uploaded_file_blocks` |
| 2 | `f97e7ae9` | Provider flatten in base + Gemini + OpenAI-native Responses paths |
| 3 | `54bc05ee` | Consumers (`refresh_context_attachments`, `remove_context_attachment`) accept both shapes |
| 4 | `6da602ef` | Flip 3 producers (`_preprocess_csv`, `_preprocess_pdf`, `_preprocess_office`) |
| 5 | `94fe67d8` | R10 cache predicate recognizes new type + session round-trip tests |
| 6 | `063499fe` | Web + VSCode client renderers |

Each stage is independently reversible.

## Client changes

- **Rich TUI** — `Message.text_content()` renders `uploaded_file` blocks as `[File: name (media_type)]` for logs, token estimates, and markdown exports.
- **Textual TUI (ppxaide)** — same; no additional wiring.
- **Web app** — `normalizeContent()` in `app.js` recognizes the new type.
- **VSCode extension** — `textContent()` in `httpClient.ts` + `normalizeContent()` in the webview's `main.js`; TypeScript `ContentBlock` interface extended with the new optional fields.

## R19 — ppxaide multimodal regression coverage (bonus)

v1.17.6 was scoped as R5-only, but writing the R19 coverage tests uncovered two real bugs the engine-layer v1.17.5/6 fixes hadn't caught:

1. **`MessageBox._normalize_content_to_text` missing `uploaded_file` branch** — R5 Stage 6 gap on the ppxaide widget side. PDFs rendered as `[uploaded_file]` instead of `[File: name (media_type)]` in the Textual chat bubble, inconsistent with the other three clients.

2. **`AppState.set()` / `update()` didn't isolate listeners** — one raising widget-listener silently skipped every subsequent listener on the same field. Now matches the `SessionManager.on_messages_changed` try/except-with-warning policy.

Both landed alongside **21 new tests in `tests/test_r19_ppxaide_multimodal.py`** covering all four R19 culprits:

- **A1 (9 tests)** — `MessageBox` rendering of mixed text+image+uploaded_file content
- **A2 (4 tests)** — full multimodal agent-turn event ordering through the dispatcher + blinker EventBus
- **A3 (4 tests)** — `pending_files` lifecycle (happy path, error path, cross-send contamination)
- **A4 (4 tests)** — `context_attachments` mid-stream listener resilience

Three of R19's four suspected culprits are now covered directly (not just indirectly through engine-layer proxies). Culprit #3 (`pending_files` stale state) uses lightweight mocks of the send-path invariants; the full Textual integration-harness version is still possible if a concrete failure ever surfaces in the field.

## Tests

- 2068 passing (was 2003 pre-R5) — +65 net, zero regressions
- New test files:
  - `tests/test_uploaded_file_block.py` (13) — schema, defensive copy, byte-identical equivalence
  - `tests/test_r5_provider_flatten.py` (9) — all three provider entry points
  - `tests/test_r5_dual_read.py` (11) — consumers handle both shapes; mixed sessions
  - `tests/test_r5_end_to_end.py` (4) — full pipeline integration
  - `tests/test_r5_session_round_trip.py` (7) — R10 cache + session save/load
  - `tests/test_r19_ppxaide_multimodal.py` (21) — ppxaide multimodal regression coverage
- Existing files updated:
  - `tests/test_file_preprocessing.py` (3 assertions flipped to new shape)
  - `tests/test_csv_tools.py` (1 assertion flipped)

## Upgrade notes

Drop-in release. No migration needed. The session format is unchanged — flat `.json` for text-only sessions, directory with `uploads/` for multimodal — and the R10 cache predicate routes `uploaded_file` blocks to the directory format automatically.

## Not in this release

- ~~R19 — ppxaide multimodal fragility investigation.~~ → **addressed in this release** via the 21-test coverage bundle above + the two fixes it surfaced. A full Textual-integration-harness stress test is still an option if field reports resurface; the point-fixable surface is now under test.

## Commits

```
a021c4c6 test(ppxaide): R19 — targeted regression coverage + two real fixes
aaf642f0 chore: bump version to v1.17.6 + CHANGELOG + release notes
063499fe feat(clients): R5 Stage 6 — web + VSCode renderers handle uploaded_file
94fe67d8 feat(session): R5 Stage 5 — R10 cache recognizes uploaded_file + round-trip tests
6da602ef feat(file-preprocessing): R5 Stage 4 — producers emit structured uploaded_file blocks
54bc05ee feat(multimodal): R5 Stage 3 — consumers accept both structured and text-marker shapes
f97e7ae9 feat(providers): R5 Stage 2 — flatten uploaded_file blocks before API calls
8c626e13 feat(engine): R5 Stage 1 — uploaded_file content-block helpers
```
