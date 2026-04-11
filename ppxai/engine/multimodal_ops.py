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
- `has_vision_model()` — config-only probe for the VL sidecar
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
import re
from typing import Any, Dict, List

from ..common.logger import get_logger
from ..config import get_vision_model_config

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
        for block in content:
            if not isinstance(block, dict):
                continue
            btype = block.get("type")
            if btype == "image_url":
                name = block.get("name") or "image"
                file_id = block.get("file_id") or ""
                # Dedup key prefers file_id (stable content-addressed
                # identity) and falls back to name for legacy blocks.
                dedup_key = file_id or name
                if dedup_key in seen_keys:
                    continue
                seen_keys.add(dedup_key)

                # Prefer authoritative metadata from the file store
                # (populated in Phase 2.1a). Falls back to parsing the
                # data URI for pure-Phase-1 content blocks.
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
                dedup_key = file_id or name
                if dedup_key in seen_keys:
                    continue
                seen_keys.add(dedup_key)
                attachments.append({
                    "name": name,
                    "kind": "file",
                    "media_type": block.get("media_type") or "",
                    "turn_index": turn_index,
                    "file_id": file_id,
                })
            elif btype == "text":
                # PDF and Office attachments produce text parts with
                # an <uploaded_file> XML marker (Phase 2.8+). Parse
                # the marker to recover name, file_id, and type for
                # the attachment badge.
                text = block.get("text") or ""
                if "<uploaded_file " in text:
                    m = re.search(
                        r'<uploaded_file\s+'
                        r'name="([^"]*)"[^>]*'
                        r'type="([^"]*)"[^>]*'
                        r'file_id="([^"]*)"',
                        text,
                    )
                    if m:
                        uf_name = m.group(1) or "file"
                        uf_type = m.group(2) or ""
                        uf_fid = m.group(3) or ""
                        dedup_key = uf_fid or uf_name
                        if dedup_key not in seen_keys:
                            seen_keys.add(dedup_key)
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


def remove_context_attachment(engine, name: str) -> int:
    """Drop all user-turn multimodal parts matching `name` from history.

    Walks `session.messages`, rewrites any user message containing an
    `image_url` or file content part whose `name` field (or file_id)
    matches the argument, and drops those parts. Messages whose
    content list becomes empty after removal get a `[Attachment
    removed: name]` text placeholder so conversation alternation stays
    valid — dropping the whole message would leave consecutive
    assistant turns and violate provider API rules.

    The SessionFileStore file_id → path mapping is intentionally NOT
    touched: other turns may still reference the same file_id, and
    cleaning up orphaned bytes is the job of `cleanup_all` at session
    teardown. Clients that want to reclaim disk space immediately can
    call `file_store.cleanup(file_id)` themselves after confirming no
    remaining message references the id.

    Fires `on_messages_changed` at the end, which refreshes the
    `context_attachments` AppState field and cascades to every
    subscribed client (Rich status bar, Textual footer, web chips,
    VSCode chips).

    Args:
        name: Attachment display name as reported by
              `get_context_attachments()`, OR the literal string
              "all" to remove every attachment in one call. Matches
              are case-insensitive for "all"; exact for names so
              files that legitimately share a prefix aren't grouped.

    Returns:
        Number of content parts removed across all messages. Zero
        indicates no matches — the caller should surface a "no
        such attachment" message rather than pretending success.
    """
    if not name:
        return 0

    remove_all = name.lower() == "all"
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
            if btype not in ("image_url", "input_file", "file"):
                kept.append(block)
                continue
            block_name = (
                block.get("name")
                or block.get("filename")
                or block.get("file_id")
                or ""
            )
            if remove_all or block_name == name:
                removed_count += 1
                had_attachment = True
                continue
            kept.append(block)

        if not had_attachment:
            continue

        # If the message now has no content parts left (a rare case
        # where a user turn was nothing but attachments), inject a
        # text placeholder so alternation stays valid.
        if not kept:
            kept.append({
                "type": "text",
                "text": f"[Attachment removed: {name}]",
            })

        msg.content = kept
        mutated = True

    if mutated:
        engine.session._notify_messages_changed()

    return removed_count


# =============================================================================
# Vision-language sidecar (v1.17.4 Phase 2.7)
# =============================================================================


def has_vision_model() -> bool:
    """Return True if a vision-language sidecar is configured and usable.

    Checks the `tools.vision_model` config section: the sidecar is
    "available" when `enabled=True`, endpoint and model are both
    non-empty, and (by default) `auto_caption=True` so file
    preprocessing calls it automatically. Callers with their own
    use policy can read `get_vision_model_config()` directly.
    """
    try:
        cfg = get_vision_model_config()
    except Exception as exc:
        logger.debug(f"has_vision_model: config read failed: {exc}")
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
    "has_vision_model",
    "caption_image",
]
