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
        content = getattr(msg, "content", None)
        if not isinstance(content, list):
            continue
        for idx, block in enumerate(content):
            if not isinstance(block, dict):
                continue
            btype = block.get("type")
            if btype == "image_url":
                # ADR 0006 Phase 2b: resolve_attachment handles the
                # AttachmentRef-first-with-in-block-fallback lookup in
                # one place — see Message.resolve_attachment docstring.
                # hasattr guard supports test stubs that don't pass
                # real Message instances.
                if hasattr(msg, "resolve_attachment"):
                    ref = msg.resolve_attachment(idx)
                    name = ref.name or "image"
                    file_id = ref.file_id or ""
                else:
                    name = block.get("name") or "image"
                    file_id = block.get("file_id") or ""

                # Content-addressed dedup (R7). When file_id is empty
                # (legacy blocks), do NOT collapse by name — two
                # different same-named files should produce two badges.
                if file_id:
                    if file_id in seen_keys:
                        continue
                    seen_keys.add(file_id)

                # Prefer authoritative metadata from the file store
                # (populated in Phase 2.1a). Falls back to parsing the
                # data URI for pure-Phase-1 content blocks. Block lookup
                # by index is still needed here — AttachmentRef carries
                # only name/file_id, not the URL we parse for media_type
                # in the file_store-unavailable case.
                media_type = ""
                if file_id and engine.file_store is not None:
                    meta = engine.file_store.get_metadata(file_id)
                    if meta is not None:
                        media_type = meta.media_type
                        # Keep the filename from the store canonical
                        # — it survives save→load round trips.
                        name = meta.name
                if not media_type:
                    url = (block.get("image_url") or {}).get("url", "")
                    if url.startswith("data:"):
                        try:
                            media_type = url[5:].split(";", 1)[0] or ""
                        except Exception:
                            media_type = ""

                attachments.append({
                    "name": name,
                    "kind": "image",
                    "media_type": media_type,
                    "turn_index": turn_index,
                    "file_id": file_id,
                })
            elif btype in ("input_file", "file"):
                name = block.get("name") or block.get("filename") or "file"
                file_id = block.get("file_id") or ""
                # Content-addressed dedup (R7) — same semantics as image_url.
                if file_id:
                    if file_id in seen_keys:
                        continue
                    seen_keys.add(file_id)
                attachments.append({
                    "name": name,
                    "kind": "file",
                    "media_type": block.get("media_type") or "",
                    "turn_index": turn_index,
                    "file_id": file_id,
                })
            elif btype == "uploaded_file":
                # R5 (v1.17.6): first-class uploaded_file content block.
                # Preferred shape for non-image attachments going forward.
                # Dedup + badge-kind rules mirror the legacy text-marker
                # branch below so the two shapes can coexist in the
                # same session (useful during the rollout and for
                # sessions loaded from pre-R5 ppxai builds).
                uf_name = block.get("name") or "file"
                uf_type = block.get("media_type") or ""
                uf_fid = block.get("file_id") or ""
                if uf_fid:
                    if uf_fid in seen_keys:
                        continue
                    seen_keys.add(uf_fid)
                kind = "pdf" if "pdf" in uf_type else "file"
                attachments.append({
                    "name": uf_name,
                    "kind": kind,
                    "media_type": uf_type,
                    "turn_index": turn_index,
                    "file_id": uf_fid,
                })
            elif btype == "text":
                # Legacy path (pre-R5): PDF/Office/large-CSV attachments
                # were embedded as `<uploaded_file>` XML markers inside
                # text blocks. Kept for backward compat — sessions saved
                # by pre-v1.17.6 code still load correctly and their
                # attachments are tracked and removable.
                text = block.get("text") or ""
                if "<uploaded_file " not in text:
                    continue
                for marker in parse_uploaded_file_markers(text):
                    uf_name = marker.get("name") or "file"
                    uf_type = marker.get("type") or ""
                    uf_fid = marker.get("file_id") or ""
                    # Dedup semantics (R7): content-addressed when
                    # file_id is present; when absent, do NOT collapse
                    # by name — two empty-file_id markers sharing a
                    # name are two distinct attachments from the user's
                    # perspective, and silently collapsing them is the
                    # badge-count bug we're fixing.
                    if uf_fid:
                        if uf_fid in seen_keys:
                            continue
                        seen_keys.add(uf_fid)
                    kind = "pdf" if "pdf" in uf_type else "file"
                    attachments.append({
                        "name": uf_name,
                        "kind": kind,
                        "media_type": uf_type,
                        "turn_index": turn_index,
                        "file_id": uf_fid,
                    })

    # AppState.set() short-circuits on equality so unchanged lists don't
    # fire listeners or SSE events.
    engine.state.set("context_attachments", attachments)


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
