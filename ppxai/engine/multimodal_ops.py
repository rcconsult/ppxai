"""
Multimodal operations — context attachment tracking + VL sidecar.

Extracted from engine/client.py (v1.17.4) to reduce EngineClient size
and co-locate all the multimodal-context code in one focused module.
All functions take an engine reference as first parameter.

Covers:
- `refresh_context_attachments(engine)` — walks session.messages and
  writes the current multimodal attachment list to AppState. Called
  from `session.on_messages_changed` after every mutation.
- `get_context_attachments(engine)` — reads the canonical AppState field
- `remove_context_attachment(engine, name)` — drops matching parts from
  user turns, with alternation-preserving placeholder injection
- `has_vision_sidecar()` — config-only probe for the VL sidecar
  (formerly `has_vision_model` — see R4 note)
- `caption_image(engine, name, media_type, data)` — one-shot VL caption
  call used by `file_preprocessing.preprocess_file` when the user
  attaches an image to a text-only model

The `refresh_context_attachments` function exposes the full role-filter
+ dedup + entry-schema contract documented on
`AppState.FIELDS["context_attachments"]`. This is the single source of
truth for the `context_attachments` field's computation; any change to
the entry schema must update the AppState schema JSON and the web/VSCode
client readers at the same time.
"""

import base64
import os
from typing import Any, Dict, List

from ..common.logger import get_logger
from ..config import get_vision_model_config
from .artifact_projector import ContextAttachmentProjector
from .types import OfficeAttachmentRef, PdfAttachmentRef
from .uploaded_file import (
    parse_uploaded_file_markers,
    strip_uploaded_file_marker,
)

logger = get_logger("engine")


# =============================================================================
# context_attachments AppState field — tracked across session mutations
# =============================================================================


def refresh_context_attachments(engine) -> None:
    """Recompute the `context_attachments` AppState field from session history.

    Called from `session.on_messages_changed` after every mutation of
    `session.messages`. Walks the history once, extracts one dict per
    unique multimodal content part, and writes the full list to
    AppState. The write is a no-op (no listener fire, no SSE push) if
    the computed list is equal to the previous value — so this is safe
    to call on every mutation, including assistant turns that never
    contain attachments.

    **Role filter (important invariant for Phase 2.8+):** only
    `role == "user"` turns contribute to `context_attachments`.
    Tool-generated images (e.g. `GetPdfPageImageTool` returning a
    rasterized PDF page, Phase 2.8; `RenderExcelChartTool`, Phase 4)
    land in `role == "tool"` or `role == "assistant"` messages and
    are deliberately excluded. Rationale: the badge represents "what
    the user attached to this conversation," not "every multimodal
    artifact in the history." A user who reads 20 PDF pages via tools
    should not see 20 entries in their badge — that would bury real
    user uploads and conflate intent (deliberate attach) with side
    effects (tool exploration). If we later want to surface tool
    artifacts as a separate badge, Phase 4 can add a `kind="tool_output"`
    variant and a second AppState field or a grouped display.

    Entry schema matches the contract documented on AppState.FIELDS:
    `{"name", "kind", "media_type", "turn_index", "file_id"}`. Keys
    are stable and JSON-serializable so web/VSCode clients can consume
    this via SSE `state_sync` without any translation. `file_id` is
    the empty string for legacy entries (Phase 1 sessions predating
    SessionFileStore); clients use it to request thumbnails from a
    future server endpoint.
    """
    attachments: List[Dict[str, Any]] = []
    seen_keys: set = set()
    for turn_index, msg in enumerate(engine.session.messages):
        # Role filter — see docstring. Tool/assistant multimodal content
        # is invisible to this scanner by design.
        if getattr(msg, "role", None) != "user":
            continue

        # ADR 0006 Step 7b (v1.18.6): all artifact dispatch goes through
        # `ContextAttachmentProjector.project(ref)`. Two ref-source paths
        # converge on the projector:
        #
        #   (A) `Message.attachments` — populated by the producer pipeline
        #       (Steps 1-3) for every multimodal Message constructed via
        #       EngineClient.chat. Also populated by `_deserialize_message`
        #       for v2 sessions (Step 4) and legacy v1 sessions (via
        #       extract_attachment_refs synthesis).
        #
        #   (B) Synthesized from raw content blocks — for in-memory
        #       Message objects built outside the producer pipeline
        #       (test fixtures, direct constructors). Synthesis happens
        #       once via `_synthesize_refs_from_content`, then dispatch
        #       is uniform with path (A).
        #
        # Plus the legacy `<uploaded_file>` text-marker branch for
        # pre-v1.17.6 sessions where attachments arrived as XML markers
        # embedded in text blocks (no content-block kind to synthesize from).
        refs = list(getattr(msg, "attachments", None) or [])
        if not refs:
            refs = _synthesize_refs_from_content(getattr(msg, "content", None))

        for ref in refs:
            entry = _project_with_media_type_enrichment(
                ref, msg.content, engine.file_store,
            )
            if entry is None:
                continue
            file_id = entry["file_id"]
            # Content-addressed dedup (R7). When file_id is empty
            # (legacy / inline blocks), do NOT collapse by name —
            # two same-named files are two distinct attachments.
            if file_id:
                if file_id in seen_keys:
                    continue
                seen_keys.add(file_id)
            entry["turn_index"] = turn_index
            attachments.append(entry)

        # Legacy text-marker fallback — pre-v1.17.6 sessions only.
        # New v1.18.6 producers don't emit these; new v2 sessions
        # don't load these. Kept to keep transition-period sessions
        # discoverable in the badge.
        content = getattr(msg, "content", None)
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict) or block.get("type") != "text":
                continue
            text = block.get("text") or ""
            if "<uploaded_file " not in text:
                continue
            for marker in parse_uploaded_file_markers(text):
                ref = _ref_from_legacy_text_marker(marker)
                if ref is None:
                    continue
                entry = ContextAttachmentProjector.project(ref)
                file_id = entry["file_id"]
                if file_id:
                    if file_id in seen_keys:
                        continue
                    seen_keys.add(file_id)
                entry["turn_index"] = turn_index
                attachments.append(entry)

    # AppState.set() short-circuits on equality so unchanged lists don't
    # fire listeners or SSE events.
    engine.state.set("context_attachments", attachments)


def _project_with_media_type_enrichment(
    ref: Any, content: Any, file_store: Any,
) -> Dict[str, Any] | None:
    """Project an artifact ref via ContextAttachmentProjector, then
    enrich `media_type` from the file store / data URI when the ref
    didn't carry one.

    The producer pipeline (Steps 1-3) populates `ref.media_type` for
    every kind today, so the enrichment branch fires only for refs
    constructed outside the pipeline (test fixtures, legacy v1 sessions
    loaded via `extract_attachment_refs` synthesis where media_type
    is empty by design).

    Returns None if the projector doesn't know this kind — caller
    skips silently for forward-compat (e.g. v1.19.x sub-agent kinds
    loaded by an older ppxai build).
    """
    entry = ContextAttachmentProjector.project_optional(ref)
    if entry is None:
        return None
    if entry.get("media_type"):
        return entry

    # Enrichment — file store wins (canonical), data URI parse next.
    file_id = entry.get("file_id") or ""
    if file_id and file_store is not None:
        meta = file_store.get_metadata(file_id)
        if meta is not None:
            entry["media_type"] = meta.media_type
            # Canonical store-name beats the ref name — survives
            # save→load round trips identically.
            entry["name"] = meta.name
            return entry

    # Last-resort: parse `data:image/png;base64,...` URI from the
    # matching content block. Only meaningful for image kind today.
    block_index = getattr(ref, "block_index", -1)
    if (
        isinstance(content, list)
        and 0 <= block_index < len(content)
        and isinstance(content[block_index], dict)
        and content[block_index].get("type") == "image_url"
    ):
        url = (content[block_index].get("image_url") or {}).get("url", "")
        if url.startswith("data:"):
            try:
                entry["media_type"] = url[5:].split(";", 1)[0] or ""
            except Exception:
                pass
    return entry


def _synthesize_refs_from_content(content: Any) -> List[Any]:
    """Build artifact refs from raw content blocks for messages whose
    `Message.attachments` field is empty.

    Used when a Message arrives outside the producer pipeline (test
    fixtures, manual constructors). Mirrors the kind dispatch the
    producer would have applied: `image_url` → ImageAttachmentRef,
    `uploaded_file` → Pdf/Office/Text ref by media_type. Empty
    `name`+`file_id` blocks are skipped (not actionable for the badge).

    The synthesis happens here (one place) so the rest of the scanner
    walks a uniform List[ArtifactRef] regardless of construction path.
    Avoids re-introducing kind-dispatch in the reader body itself.
    """
    if not isinstance(content, list):
        return []
    refs: List[Any] = []
    # Local import — avoid circular dep at module load (artifact_projections
    # imports types which imports artifact_registry which... etc.)
    from .types import ImageAttachmentRef, TextAttachmentRef

    for idx, block in enumerate(content):
        if not isinstance(block, dict):
            continue
        btype = block.get("type")
        name = block.get("name") or block.get("filename") or ""
        file_id = block.get("file_id") or ""
        media_type = block.get("media_type") or ""

        if btype == "image_url":
            # Image blocks always synthesize a ref even when name+file_id
            # are both empty — the badge surfaces a generic "image"
            # entry so users see SOMETHING attached. Pre-Step-7b
            # behavior; preserved for parity. Non-image kinds skip
            # silently because their badge would be misleading without
            # a name (no way for the user to identify what's there).
            refs.append(ImageAttachmentRef(
                block_index=idx, name=name or "image",
                file_id=file_id, media_type=media_type,
            ))
        elif btype == "uploaded_file":
            if not name and not file_id:
                continue
            if "pdf" in media_type:
                refs.append(PdfAttachmentRef(
                    block_index=idx, name=name or "file",
                    file_id=file_id, media_type=media_type,
                ))
            else:
                # Includes input_file, file, and any non-PDF uploaded_file
                # — collapses to OfficeAttachmentRef for projector dispatch.
                # Pre-Step-7b code mapped these to kind="file" too.
                refs.append(OfficeAttachmentRef(
                    block_index=idx, name=name or "file",
                    file_id=file_id, media_type=media_type,
                ))
        elif btype in ("input_file", "file"):
            if not name and not file_id:
                continue
            # input_file/file blocks are first-party OpenAI shapes that
            # arrive outside the v1.18.6 producer pipeline. Map to
            # OfficeAttachmentRef (kind="office", projects as kind="file"
            # in DTO — preserving pre-Step-7b mapping).
            refs.append(OfficeAttachmentRef(
                block_index=idx, name=name or "file",
                file_id=file_id, media_type=media_type,
            ))
    return refs


def _ref_from_legacy_text_marker(marker: Dict[str, str]) -> Any:
    """Synthesize a kind-specific MarshallableArtifact from a parsed
    `<uploaded_file>` XML marker (pre-v1.17.6 session shape).

    Lets the legacy text-marker branch reuse the same projector
    dispatch as the modern Message.attachments path — no kind-specific
    if/elif in the scanner. Marker `type` discriminates between PDF
    and other documents, matching the pre-Step-7b kind mapping
    (`"pdf" if "pdf" in type else "file"`).

    Returns None for malformed markers (no name + no file_id) so
    the scanner can skip silently.
    """
    name = marker.get("name") or ""
    file_id = marker.get("file_id") or ""
    media_type = marker.get("type") or ""
    if not name and not file_id:
        return None
    # Synthesize block_index = -1 sentinel — legacy text markers
    # don't have a corresponding content block index in the v1.18.6
    # sense. Projector handlers don't read block_index, so this is
    # purely diagnostic.
    if "pdf" in media_type:
        return PdfAttachmentRef(
            block_index=-1, name=name, file_id=file_id, media_type=media_type,
        )
    return OfficeAttachmentRef(
        block_index=-1, name=name, file_id=file_id, media_type=media_type,
    )


def get_context_attachments(engine) -> List[Dict[str, Any]]:
    """Return the current multimodal attachments in conversation context.

    Reads from AppState — the canonical source maintained by
    `refresh_context_attachments`. Clients should prefer this method
    (or subscribing to the `context_attachments` AppState field
    directly) over scanning `session.messages` themselves, so all
    four clients render identical data.
    """
    return list(engine.state.get("context_attachments") or [])


def remove_context_attachment(engine, target: str) -> int:
    """Drop all user-turn multimodal parts matching `target` from history.

    Matches across three attachment surfaces:
      * structured blocks (`image_url`, `input_file`, `file`)
      * `<uploaded_file>` markers embedded in `text` blocks (PDF/Office)

    Matching rules (R7). The function first resolves `target` to a
    **file_id** using the current `context_attachments` index:

      * `target == "all"` → remove every attachment (all surfaces).
      * `target` equals an attachment's `file_id` → remove by file_id
        (exact, unambiguous).
      * `target` equals a `short_id` (last 8+ chars of a `file_id`) →
        remove by that file_id.
      * `target` equals an attachment's `name` → remove every block/
        marker sharing that name. Callers that want to disambiguate
        must pass the file_id or short_id explicitly; the command
        layer is responsible for surfacing an AMBIGUOUS warning to
        the user before calling here (see
        `commands/attach.py::_handle_attach_remove`).

    Messages whose content list becomes empty after removal get a
    `[Attachment removed: <target>]` text placeholder so conversation
    alternation stays valid — dropping the whole message would leave
    consecutive assistant turns and violate provider API rules.

    SessionFileStore bytes are intentionally NOT cleaned up here;
    other turns may still reference the same file_id.

    Fires `on_messages_changed` which refreshes `context_attachments`
    and cascades to every subscribed client.

    Args:
        target: file_id, short_id, display name, or "all".

    Returns:
        Number of content parts / markers removed across all messages.
    """
    if not target:
        return 0

    remove_all = target.lower() == "all"

    # Resolve the caller's target to a concrete match set.
    #
    # We match against the current AppState view (the same data that
    # clients see in their badge) so "remove what I can see" semantics
    # hold. The matcher collects file_ids + names so the block-level
    # pass below can use either.
    matched_file_ids: set = set()
    matched_names: set = set()
    if not remove_all:
        attachments = get_context_attachments(engine)
        for entry in attachments:
            fid = entry.get("file_id") or ""
            name_ = entry.get("name") or ""
            # Exact file_id match (preferred).
            if fid and target == fid:
                matched_file_ids.add(fid)
                continue
            # short_id match — suffix of file_id, min 8 chars so we
            # don't accidentally match short strings.
            if fid and len(target) >= 8 and fid.endswith(target):
                matched_file_ids.add(fid)
                continue
            # Name match (may hit multiple entries — intentional; the
            # command layer is expected to have filtered AMBIGUOUS
            # cases out before calling here).
            if name_ and target == name_:
                matched_names.add(name_)
                if fid:
                    matched_file_ids.add(fid)

    def _block_matches(block: Dict[str, Any]) -> bool:
        """True if this structured block should be removed."""
        fid = block.get("file_id") or ""
        bname = block.get("name") or block.get("filename") or ""
        if fid and fid in matched_file_ids:
            return True
        if bname and bname in matched_names and not fid:
            # Fall-back for legacy blocks that never made it into the
            # file store — name-only identity, same collision caveat.
            return True
        # Last-ditch: target typed literally as "name.ext" matches a
        # legacy block whose only identifier is its name.
        if not fid and bname == target:
            return True
        return False

    removed_count = 0
    mutated = False

    for msg in engine.session.messages:
        if getattr(msg, "role", None) != "user":
            continue
        content = getattr(msg, "content", None)
        if not isinstance(content, list):
            continue

        kept: List[Dict[str, Any]] = []
        had_attachment = False
        for block in content:
            if not isinstance(block, dict):
                kept.append(block)
                continue
            btype = block.get("type")

            # Structured attachment blocks — drop on match.
            if btype in ("image_url", "input_file", "file"):
                if remove_all or _block_matches(block):
                    removed_count += 1
                    had_attachment = True
                    continue
                kept.append(block)
                continue

            # R5 (v1.17.6): first-class uploaded_file block — same
            # dispatch as image_url/input_file/file. `_block_matches`
            # already reads `name` / `file_id` keys from the block so
            # no special handling is needed beyond dispatching here.
            if btype == "uploaded_file":
                if remove_all or _block_matches(block):
                    removed_count += 1
                    had_attachment = True
                    continue
                kept.append(block)
                continue

            # Text blocks may contain one or more <uploaded_file>
            # markers (PDF/Office). Strip matching markers; keep the
            # surrounding text if any remains.
            if btype == "text":
                text = block.get("text") or ""
                if "<uploaded_file " not in text:
                    kept.append(block)
                    continue

                if remove_all:
                    # Strip every marker from this text block; keep any
                    # surrounding user text that remains.
                    from .uploaded_file import UPLOADED_FILE_RE
                    stripped_text = UPLOADED_FILE_RE.sub("", text).strip()
                    marker_count = len(parse_uploaded_file_markers(text))
                    removed_count += marker_count
                    had_attachment = marker_count > 0
                    if stripped_text:
                        new_block = dict(block)
                        new_block["text"] = stripped_text
                        kept.append(new_block)
                    # else: drop the whole block
                    continue

                # Targeted removal: strip each matched marker.
                new_text = text
                local_removed = 0
                for fid in matched_file_ids:
                    new_text, n = strip_uploaded_file_marker(
                        new_text, file_id=fid
                    )
                    local_removed += n
                if local_removed == 0 and matched_names:
                    # Name-only fallback (legacy markers without file_id
                    # OR when caller passed a literal name).
                    for n_ in matched_names:
                        new_text, n = strip_uploaded_file_marker(
                            new_text, name=n_
                        )
                        local_removed += n

                if local_removed > 0:
                    removed_count += local_removed
                    had_attachment = True
                    stripped = new_text.strip()
                    if stripped:
                        new_block = dict(block)
                        new_block["text"] = stripped
                        kept.append(new_block)
                    # else: drop the whole block
                else:
                    kept.append(block)
                continue

            # Any other block type passes through untouched.
            kept.append(block)

        if not had_attachment:
            continue

        # If the message now has no content parts left, inject a text
        # placeholder so alternation stays valid.
        if not kept:
            kept.append({
                "type": "text",
                "text": f"[Attachment removed: {target}]",
            })

        msg.content = kept
        mutated = True

    if mutated:
        engine.session._notify_messages_changed()

    return removed_count


# =============================================================================
# Vision-language sidecar (v1.17.4 Phase 2.7)
# =============================================================================


def has_vision_sidecar() -> bool:
    """Return True if a vision-language **sidecar** is configured and usable.

    Note the name: this checks the `tools.vision_model` config section,
    NOT whether the currently active model is vision-capable. For
    "does my model understand images natively?" use
    `model_profiles.get_profile(model).supports_vision` instead
    (see R4 in TODO-file-upload.md for the original naming confusion).

    The sidecar is "available" when `enabled=True`, endpoint and model
    are both non-empty, and (by default) `auto_caption=True` so file
    preprocessing calls it automatically. Callers with their own
    use policy can read `get_vision_model_config()` directly.
    """
    try:
        cfg = get_vision_model_config()
    except Exception as exc:
        logger.debug(f"has_vision_sidecar: config read failed: {exc}")
        return False
    return (
        bool(cfg.get("enabled"))
        and bool(cfg.get("endpoint"))
        and bool(cfg.get("model"))
    )


def caption_image(
    engine,
    name: str,
    media_type: str,
    data: bytes,
) -> str:
    """One-shot VL caption call for a single image.

    Used by `file_preprocessing.preprocess_file` when the user
    attaches an image while chatting with a text-only model. Sends
    a single `/chat/completions` request to the configured VL
    endpoint with the image as an `image_url` data URI and a
    concise "describe this" system prompt, and returns the plain
    text caption.

    Any failure (sidecar disabled, network error, malformed
    response, timeout) returns an empty string so
    `file_preprocessing` falls through to its placeholder path
    rather than aborting the whole attachment. Warnings are logged
    for diagnostic purposes.

    The `engine` parameter is unused today but kept in the signature
    for symmetry with the rest of this module and to give future
    implementations (caching, rate limiting, per-session auth) a
    place to hang state without breaking callers.

    Args:
        engine: EngineClient reference (currently unused).
        name: Display name of the image (used only for log messages).
        media_type: MIME type of the image bytes (e.g. "image/png").
        data: Raw image bytes.

    Returns:
        A caption string on success, or "" on any failure.
    """
    del engine  # reserved for future caching / per-session state
    cfg = get_vision_model_config()
    if not cfg.get("enabled") or not cfg.get("endpoint") or not cfg.get("model"):
        return ""

    endpoint = cfg["endpoint"].rstrip("/")

    # Build the request. We use the OpenAI SDK for consistency with
    # how ppxai talks to every other provider, rather than raw
    # httpx — the SDK handles retries, auth headers, and error
    # translation for us.
    try:
        from openai import OpenAI  # noqa: PLC0415
    except ImportError:
        logger.warning("caption_image: openai SDK not installed")
        return ""

    api_key = ""
    api_key_env = cfg.get("api_key_env") or ""
    if api_key_env:
        api_key = os.environ.get(api_key_env, "")
    # OpenAI SDK requires a non-empty api_key even for no-auth
    # endpoints; use a placeholder for local servers.
    if not api_key:
        api_key = "local-sidecar"

    b64 = base64.b64encode(data).decode("ascii")
    data_uri = f"data:{media_type};base64,{b64}"

    try:
        client = OpenAI(
            base_url=endpoint if endpoint.endswith("/v1") else f"{endpoint}/v1",
            api_key=api_key,
            timeout=float(cfg.get("timeout", 30)),
        )
        response = client.chat.completions.create(
            model=cfg["model"],
            max_tokens=int(cfg.get("max_tokens", 200)),
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": cfg.get("prompt", "Describe this image.")},
                        {"type": "image_url", "image_url": {"url": data_uri}},
                    ],
                }
            ],
        )
    except Exception as exc:
        logger.warning(f"caption_image: VL call failed for {name}: {exc}")
        return ""

    try:
        caption = response.choices[0].message.content or ""
    except (AttributeError, IndexError):
        logger.warning(
            f"caption_image: unexpected response shape for {name}"
        )
        return ""

    caption = caption.strip()
    logger.debug(
        f"caption_image: {name} → {len(caption)} chars via "
        f"{cfg['endpoint']} ({cfg['model']})"
    )
    return caption


__all__ = [
    "refresh_context_attachments",
    "get_context_attachments",
    "remove_context_attachment",
    "has_vision_sidecar",
    "caption_image",
]
