"""
/attach slash command — stage files for the next chat turn.

Usage:
    /attach <path> [path2] ...   — stage one or more files
    /attach                       — list currently staged files
    /attach clear                 — discard all staged files

Staged files live on the CommandHandler (`handler.pending_files`) and are
consumed by the Rich TUI send loop, which builds a multimodal Message.content
list mixing the user's text and attachment parts. The list is cleared after
each chat send.

Phase 1 scope (v1.17.4):
- Images (PNG/JPEG/WEBP/GIF) → `image_url` content parts sent as data: URIs.
  Shown inline via ITerm2/Sixel when the terminal supports it.
- Text/code files → inlined into a `<file name="…">…</file>` text block so
  every provider (not just vision models) can read them.

PDFs and Office documents are deferred to Phase 2, where SessionFileStore and
the extraction tools land. Attempting to attach one in Phase 1 produces a
clear error asking the user to wait for Phase 2 or paste the text.
"""

from __future__ import annotations

import base64
import difflib
import mimetypes
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..common.logger import get_logger
from ..engine.file_preprocessing import preprocess_file
from ..engine.image_validation import validate_image
from .factory import CommandFactory, CommandSpec
from .results import (
    CommandResult,
    ErrorResult,
    NotificationResult,
    ResultStatus,
)

_attach_logger = get_logger("attach")

# Ensure modern extensions mimetypes doesn't know about by default.
mimetypes.add_type("image/webp", ".webp")
mimetypes.add_type("text/markdown", ".md")
mimetypes.add_type("text/markdown", ".markdown")

# 10 MB per file. Rejected above this to avoid base64-bloating very large
# payloads into provider requests. Matches the limit documented in Phase 2.
MAX_FILE_BYTES = 10 * 1024 * 1024

# Image formats that every major vision-capable provider accepts.
IMAGE_MIME_TYPES = frozenset({
    "image/png",
    "image/jpeg",
    "image/webp",
    "image/gif",
})

# Formats that Phase 1 cannot preprocess yet — point the user at Phase 2.
_DEFERRED_EXTENSIONS = frozenset({
    ".pdf", ".xlsx", ".xls", ".pptx", ".ppt", ".docx", ".doc",
})


@dataclass
class PendingFile:
    """A file staged by /attach, waiting to be sent on the next chat turn.

    Attributes:
        name: Basename used in display and as the content-part `name` field
        path: Absolute path on disk (kept for re-rendering / debugging)
        media_type: MIME type (e.g. "image/png", "text/plain")
        size: File size in bytes
        kind: Broad category from `session_store.classify_kind` ("image",
              "text", "pdf", "office", "other") — controls the send-loop
              routing decision in `build_multimodal_content`.
        data: Raw file bytes, read once at attach time and kept in memory
              until `build_multimodal_content` calls the preprocessing
              dispatcher with them. Previous versions stored pre-base64'd
              strings (`data_b64`) and pre-decoded text, but routing
              through `preprocess_file` at send time benefits from having
              the canonical bytes in one place.
        file_id: SessionFileStore identifier (v1.17.4 Phase 2.1a) — set
                 when the engine's file_store is available at attach time
                 so downstream message content can carry a compact
                 file_id reference. Empty string when staging without a
                 store (fallback path used by tests and legacy callers).
    """
    name: str
    path: str
    media_type: str
    size: int
    kind: str
    data: bytes = b""
    file_id: str = ""

    # Backward-compat shims for callers that still read the Phase-1
    # fields directly. Both properties decode on demand from `self.data`
    # so tests and old renderers keep working without an explicit
    # migration. New code should use `self.data` + `preprocess_file`.
    @property
    def data_b64(self) -> str:
        """Base64-encoded bytes (Phase 1 compat)."""
        if not self.data:
            return ""
        return base64.b64encode(self.data).decode("ascii")

    @property
    def text(self) -> str:
        """UTF-8 decoded text with normalised newlines (Phase 1 compat,
        text kind only).

        Windows writes `\r\n` line endings; LLMs and downstream text
        tooling expect `\n`. Normalise at the decode boundary so the
        attach pipeline behaves identically on every platform — a user
        /attach'ing a Windows-edited file shouldn't pay extra tokens or
        break parsers expecting LF.
        """
        if self.kind != "text" or not self.data:
            return ""
        try:
            decoded = self.data.decode("utf-8")
        except UnicodeDecodeError:
            decoded = self.data.decode("utf-8", errors="replace")
        # CRLF → LF, then bare CR → LF (classic-Mac exports).
        return decoded.replace("\r\n", "\n").replace("\r", "\n")


@dataclass
class ContextAttachment:
    """Lightweight view of a multimodal part already committed to session history.

    Distinct from `PendingFile`: a `PendingFile` is staged (pre-send) and can
    still be dropped via `/attach clear`. A `ContextAttachment` is baked into
    `session.messages` from a prior turn — it gets re-sent to the provider on
    every subsequent chat call (and re-billed), so the status bar surfaces it
    for the whole conversation, not just between attach and send.

    Attributes:
        name: Display name (pulled from the content-part's `name` field)
        kind: Currently always "image" — text file attachments merge into the
              user prompt text at send time, leaving no distinct part to track.
    """
    name: str
    kind: str = "image"


def _guess_media_type(path: Path) -> str:
    mt, _ = mimetypes.guess_type(path.name)
    return mt or "application/octet-stream"


def _classify(media_type: str, suffix: str) -> str:
    """Return 'image', 'text', or 'deferred' based on MIME type and suffix."""
    if media_type in IMAGE_MIME_TYPES:
        return "image"
    if media_type.startswith("text/"):
        return "text"
    # Common code files that mimetypes doesn't always recognize.
    if suffix in {".py", ".js", ".ts", ".tsx", ".jsx", ".go", ".rs", ".c",
                  ".cpp", ".h", ".hpp", ".java", ".kt", ".swift", ".rb",
                  ".sh", ".zsh", ".bash", ".ps1", ".lua", ".sql", ".toml",
                  ".yaml", ".yml", ".json", ".xml", ".ini", ".cfg", ".conf",
                  ".env", ".tf", ".tfvars", ".hcl", ".dockerfile", ".makefile"}:
        return "text"
    if suffix in _DEFERRED_EXTENSIONS:
        return "deferred"
    return "deferred"


def _load_file(
    raw_path: str,
    working_dir: Optional[str],
    file_store: Any = None,
) -> tuple[Optional[PendingFile], Optional[str]]:
    """Resolve and load a single file, returning (pending, error_message).

    Relative paths resolve against the command context's working_dir so the
    user can type `/attach chart.png` from any subdirectory of their project.

    When `file_store` is provided (v1.17.4 Phase 2.1a), image bytes are
    immediately registered with SessionFileStore so the returned
    PendingFile carries a stable `file_id`. That ID flows through
    `build_multimodal_content` into the content-part `file_id` field, and
    session serialization uses it to swap inline base64 for compact
    references.

    v1.17.4 Phase 2.2: image attachments are validated immediately via
    `validate_image` so the user gets instant feedback on format/size
    errors rather than discovering them only at send time. The raw bytes
    are kept on the PendingFile for `build_multimodal_content` to hand
    off to `preprocess_file` at send time — that second pass does the
    model-specific vision routing decision which can't be made here
    because the user might switch models between /attach and their
    first chat message.
    """
    # Strip surrounding quotes users sometimes paste (e.g. from file managers).
    cleaned = raw_path.strip().strip('"').strip("'")
    if not cleaned:
        return None, "empty path"

    path = Path(cleaned).expanduser()
    if not path.is_absolute() and working_dir:
        path = Path(working_dir) / path

    try:
        path = path.resolve()
    except OSError as exc:
        return None, f"cannot resolve '{cleaned}': {exc}"

    if not path.exists():
        return None, _not_found_error(path)
    if not path.is_file():
        return None, f"not a file: {path}"

    size = path.stat().st_size
    if size > MAX_FILE_BYTES:
        mb = size / (1024 * 1024)
        return None, (
            f"{path.name} is {mb:.1f} MB — exceeds the "
            f"{MAX_FILE_BYTES // (1024 * 1024)} MB attachment limit"
        )

    media_type = _guess_media_type(path)
    kind = _classify(media_type, path.suffix.lower())

    if kind == "deferred":
        return None, (
            f"{path.name} ({media_type or path.suffix}) is not supported yet. "
            "PDF / Excel / PowerPoint / Word attachments land in Phase 2 "
            "(SessionFileStore + extraction tools). For now, paste the text "
            "or export to markdown."
        )

    try:
        data = path.read_bytes()
    except OSError as exc:
        return None, f"cannot read {path.name}: {exc}"

    if kind == "image":
        # Early image validation (Phase 2.6) — catches malformed /
        # wrong-format files at attach time so the user gets feedback
        # before typing a prompt. Provider is unknown at attach time
        # (user might switch models before sending) so we use the
        # default 10 MB limit here; send-time preprocessing will re-run
        # validation with the live provider for tighter caps.
        validation = validate_image(data, declared_media_type=media_type)
        if not validation.ok:
            return None, f"{path.name}: {validation.reason}"

        # Canonical media type from magic bytes — overrides the
        # filename-derived guess if the file was mislabeled.
        media_type = validation.media_type or media_type

        # Register with the engine's file store if available. The store
        # is content-addressed, so re-attaching the same file within a
        # session reuses the existing file_id (dedup). Failures here
        # shouldn't abort the attach — PendingFile still carries the
        # raw bytes so send-time preprocessing can retry the save.
        file_id = ""
        if file_store is not None:
            try:
                meta = file_store.save(path.name, data, media_type=media_type)
                file_id = meta.file_id
            except OSError as exc:
                _attach_logger.warning(
                    f"file_store.save failed for {path.name}: {exc} — "
                    "will retry at send time"
                )

        return PendingFile(
            name=path.name,
            path=str(path),
            media_type=media_type,
            size=size,
            kind="image",
            data=data,
            file_id=file_id,
        ), None

    # Text/code file — keep raw bytes; preprocessing handles UTF-8 decode
    # and the <file> wrapper at send time.
    return PendingFile(
        name=path.name,
        path=str(path),
        media_type=media_type,
        size=size,
        kind="text",
        data=data,
    ), None


def _not_found_error(path: Path) -> str:
    """Build a file-not-found error message with close-match suggestions (R18).

    When `/attach resources/foo.png` fails because the file lives in
    `docs/`, the bare "no such file" message forces the user to retry
    blindly. This walks up the path to the first existing ancestor and
    offers the 5 closest matches (files if the parent exists, directories
    otherwise), so the next guess is an informed one.
    """
    base = f"no such file: {path}"

    parent = path.parent
    if parent.exists() and parent.is_dir():
        # Parent dir exists — suggest similar files within it.
        try:
            candidates = os.listdir(parent)
        except OSError:
            return base
        matches = difflib.get_close_matches(path.name, candidates, n=5, cutoff=0.3)
        if matches:
            return f"{base}\n  Nearest matches in {parent}/: {', '.join(matches)}"
        return f"{base} (parent dir {parent}/ has {len(candidates)} entries, none similar)"

    # Parent doesn't exist — walk up to the first existing ancestor and
    # suggest sibling directories there. This is the common "user typed
    # the wrong subdirectory" case (e.g. resources/ vs docs/).
    ancestor = parent
    missing_segment = parent.name
    while ancestor and not ancestor.exists():
        missing_segment = ancestor.name or missing_segment
        if ancestor.parent == ancestor:  # root
            break
        ancestor = ancestor.parent

    if not ancestor.exists() or not ancestor.is_dir():
        return base

    try:
        siblings = [
            name for name in os.listdir(ancestor)
            if (ancestor / name).is_dir()
        ]
    except OSError:
        return base
    matches = difflib.get_close_matches(missing_segment, siblings, n=5, cutoff=0.3)
    if matches:
        return (
            f"{base}\n  '{missing_segment}' not found under {ancestor}/. "
            f"Did you mean: {', '.join(matches)}?"
        )
    return base


def _fmt_size(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} KB"
    return f"{n / (1024 * 1024):.1f} MB"


def _summary_lines(pending: List[PendingFile]) -> List[str]:
    lines = []
    for i, pf in enumerate(pending, 1):
        kind_icon = "🖼" if pf.kind == "image" else "📄"
        lines.append(f"  {i}. {kind_icon} {pf.name} ({pf.media_type}, {_fmt_size(pf.size)})")
    return lines


def _get_pending_files(context: Any) -> List[PendingFile]:
    """Return the staged-file list, creating it on the wrapped handler if absent.

    Stored on the underlying CommandHandler (via the proxy) so state survives
    across command invocations within one REPL session.
    """
    pending = getattr(context, "pending_files", None)
    if pending is None:
        # Install on the wrapped handler; the proxy forwards attribute writes
        # to the wrapped object via the __getattr__ chain only for reads, so
        # go through _wrapped explicitly.
        target = getattr(context, "_wrapped", context)
        pending = []
        try:
            target.pending_files = pending
        except AttributeError:
            # Context doesn't allow attribute assignment — return an ephemeral
            # list (state will be lost after this call, but the command still
            # produces a useful error message).
            pass
    return pending


def _handle_attach_list(context: Any, pending: List[PendingFile]) -> CommandResult:
    """Render the combined staging + in-context attachment listing.

    Shows two sections when relevant:
    1. Staged (pre-send) — files added via /attach but not yet sent
    2. In context (post-send) — files committed to session.messages
       that the model is still re-sending (and re-billing) on every turn

    Users can tell at a glance which attachments are still racking up
    token cost vs which are about to be sent.
    """
    # Pull in-context attachments from AppState (single source of truth).
    engine_client = getattr(context, "engine_client", None)
    in_context: List[Dict[str, Any]] = []
    if engine_client is not None and hasattr(engine_client, "get_context_attachments"):
        in_context = engine_client.get_context_attachments()

    if not pending and not in_context:
        return NotificationResult(
            status=ResultStatus.INFO,
            message=(
                "No files attached.\n\n"
                "Usage:\n"
                "  /attach <path> [path2] ...  stage files for next message\n"
                "  /attach                     list staged + in-context attachments\n"
                "  /attach clear               discard staging buffer (pre-send)\n"
                "  /attach remove <name>       evict a committed attachment\n"
                "  /attach remove all          evict every committed attachment\n\n"
                "Supported: images (PNG/JPEG/WEBP/GIF), text/code, PDF."
            ),
        )

    lines: List[str] = []
    if pending:
        lines.append(
            f"Staged ({len(pending)} file{'s' if len(pending) != 1 else ''}, "
            f"will be sent with your next message):"
        )
        lines.extend(_summary_lines(pending))

    if in_context:
        if lines:
            lines.append("")
        lines.append(
            f"In context ({len(in_context)} attachment"
            f"{'s' if len(in_context) != 1 else ''}, re-sent every turn):"
        )
        for i, entry in enumerate(in_context, 1):
            name = entry.get("name", "?")
            kind = entry.get("kind", "image")
            media_type = entry.get("media_type", "")
            icon = "🖼" if kind == "image" else "📄"
            mt_suffix = f" ({media_type})" if media_type else ""
            lines.append(f"  {i}. {icon} {name}{mt_suffix}")
        lines.append("")
        lines.append("Use /attach remove <name> to evict one, or /attach remove all.")

    return NotificationResult(
        status=ResultStatus.INFO,
        message="\n".join(lines),
    )


def _short_id(file_id: str) -> str:
    """Return the last 8 chars of a file_id for user-facing disambiguation."""
    return file_id[-8:] if file_id and len(file_id) >= 8 else file_id


def _handle_attach_remove(context: Any, target: str) -> CommandResult:
    """Evict one or all committed attachments from session history.

    Matching precedence (R1 + R7 fix):
      1. `target == "all"` → wipe everything.
      2. `target` is a full file_id or an 8+ char short_id suffix → exact
         removal of that one attachment.
      3. `target` matches exactly one attachment by name → remove it.
      4. `target` matches multiple attachments by name → **AMBIGUOUS**.
         We do NOT silently remove all — we surface each candidate's
         short_id so the user can retry with the specific one.

    Delegates to `EngineClient.remove_context_attachment` which walks
    `session.messages`, drops matching content parts (and strips
    `<uploaded_file>` markers from text blocks), and fires the
    `on_messages_changed` callback to refresh AppState.
    """
    if not target:
        return ErrorResult(
            status=ResultStatus.ERROR,
            message=(
                "Missing argument.\n\n"
                "Usage:\n"
                "  /attach remove <name>       evict an attachment by name\n"
                "  /attach remove <short_id>   evict by 8+ char id suffix (disambiguates)\n"
                "  /attach remove all          evict every committed attachment"
            ),
        )

    engine_client = getattr(context, "engine_client", None)
    if engine_client is None or not hasattr(engine_client, "remove_context_attachment"):
        return ErrorResult(
            status=ResultStatus.ERROR,
            message=(
                "/attach remove requires an engine client with context "
                "attachment support."
            ),
        )

    # Detect name-collision ambiguity BEFORE asking the engine to remove
    # anything. The engine will happily wipe every same-named entry if
    # we let it — which was the R7 footgun.
    if target.lower() != "all" and hasattr(engine_client, "get_context_attachments"):
        current = engine_client.get_context_attachments()
        # Is target an exact file_id / short_id match? If so, skip
        # ambiguity check — caller is already disambiguating.
        is_id_match = any(
            (entry.get("file_id") == target) or
            (entry.get("file_id") and len(target) >= 8 and entry.get("file_id","").endswith(target))
            for entry in current
        )
        if not is_id_match:
            name_matches = [e for e in current if e.get("name") == target]
            if len(name_matches) > 1:
                lines = [
                    f"Ambiguous: {len(name_matches)} attachments named {target!r}.",
                    "",
                    "Retry with a short_id suffix to target one:",
                ]
                for e in name_matches:
                    fid = e.get("file_id") or ""
                    short = _short_id(fid) if fid else "(no file_id)"
                    kind = e.get("kind", "?")
                    mt = e.get("media_type", "")
                    turn = e.get("turn_index", "?")
                    lines.append(
                        f"  /attach remove {short}   "
                        f"[{kind}, {mt}, turn {turn}]"
                    )
                lines.append("")
                lines.append("Or /attach remove all to wipe every attachment.")
                return NotificationResult(
                    status=ResultStatus.WARNING,
                    message="\n".join(lines),
                )

    removed = engine_client.remove_context_attachment(target)
    if removed == 0:
        # Surface the available names so the user can retry with a
        # correct argument.
        current = engine_client.get_context_attachments() if hasattr(
            engine_client, "get_context_attachments"
        ) else []
        if current:
            names = ", ".join(entry.get("name", "?") for entry in current)
            return NotificationResult(
                status=ResultStatus.WARNING,
                message=(
                    f"No attachment matched {target!r}.\n"
                    f"Currently in context: {names}"
                ),
            )
        return NotificationResult(
            status=ResultStatus.INFO,
            message="No attachments currently in context.",
        )

    descriptor = "attachments" if target.lower() == "all" else f"part{'s' if removed != 1 else ''}"
    return NotificationResult(
        status=ResultStatus.SUCCESS,
        message=(
            f"Removed {removed} {descriptor} "
            f"{'across all turns' if target.lower() == 'all' else f'matching {target!r}'} "
            f"from session history."
        ),
    )


def handle_attach(context: Any, args: str) -> CommandResult:
    """Handle /attach — stage, list, clear, or remove attachments.

    Subcommands:
        /attach <path> [path2] ...  stage files for next message
        /attach                     list staged files + in-context attachments
        /attach clear               discard staging buffer (pre-send)
        /attach remove <name>       evict an already-committed attachment
                                    from session history (post-send)
        /attach remove all          evict every committed attachment
    """
    pending = _get_pending_files(context)

    args = (args or "").strip()

    # Subcommand: /attach clear — discards the pre-send staging buffer
    # only. Does NOT affect attachments already committed to message
    # history via a previous chat turn — use `/attach remove` for those.
    if args.lower() == "clear":
        count = len(pending)
        pending.clear()
        if count == 0:
            return NotificationResult(
                status=ResultStatus.INFO,
                message="No attachments to clear.",
            )
        return NotificationResult(
            status=ResultStatus.SUCCESS,
            message=f"Cleared {count} attachment{'s' if count != 1 else ''}.",
        )

    # Subcommand: /attach remove <name> | /attach remove all
    # Evicts attachments from committed session history (post-send).
    # This is the dual of `/attach clear`: clear drops staged files
    # before they hit the engine, remove drops attachments after they've
    # been committed to session.messages — stops re-sending (and
    # re-billing) an image on every subsequent turn.
    if args.lower().startswith("remove"):
        return _handle_attach_remove(context, args[len("remove"):].strip())

    # No args: list currently staged files AND in-context attachments.
    if not args:
        return _handle_attach_list(context, pending)

    # Parse paths. Support simple quoting so paths with spaces work:
    #   /attach "My Docs/chart.png"
    paths = _split_paths(args)
    if not paths:
        return ErrorResult(
            status=ResultStatus.ERROR,
            message="No valid file paths provided.",
        )

    working_dir = getattr(context, "working_dir", None) or None
    # Pick up the engine's SessionFileStore via the context adapter.
    # The attribute is optional for backward-compat with contexts that
    # don't expose an engine_client (bare test stubs, etc.).
    engine_client = getattr(context, "engine_client", None)
    file_store = getattr(engine_client, "file_store", None) if engine_client else None

    added: List[PendingFile] = []
    errors: List[str] = []
    for raw in paths:
        pf, err = _load_file(raw, working_dir, file_store=file_store)
        if err:
            errors.append(err)
            continue
        pending.append(pf)
        added.append(pf)

    if not added and errors:
        return ErrorResult(
            status=ResultStatus.ERROR,
            message="No files attached.\n" + "\n".join(f"  • {e}" for e in errors),
        )

    lines = [f"Attached {len(added)} file{'s' if len(added) != 1 else ''}:"]
    lines.extend(_summary_lines(added))
    if errors:
        lines.append("")
        lines.append("Skipped:")
        for e in errors:
            lines.append(f"  • {e}")
    lines.append("")
    lines.append("Will be sent with your next message.")

    # Metadata carries image paths so the Rich client can render an inline
    # preview right after /attach completes without re-reading the files.
    return NotificationResult(
        status=ResultStatus.SUCCESS,
        message="\n".join(lines),
        metadata={"attached_paths": [pf.path for pf in added if pf.kind == "image"]},
    )


def _split_paths(args: str) -> List[str]:
    """Split `/attach` args into individual paths, honoring simple quoting.

    Supports double-quoted paths with spaces; everything else is whitespace-
    separated. Keeps the implementation deliberately small — shlex would also
    try to interpret backslashes, which breaks Windows paths.
    """
    paths: List[str] = []
    current: List[str] = []
    in_quote = False
    for ch in args:
        if ch == '"':
            in_quote = not in_quote
            continue
        if ch.isspace() and not in_quote:
            if current:
                paths.append("".join(current))
                current = []
            continue
        current.append(ch)
    if current:
        paths.append("".join(current))
    return paths


def collect_context_attachments(session: Any) -> List[ContextAttachment]:
    """Scan a session's messages for multimodal attachments still in context.

    Standalone fallback used in tests and contexts where no EngineClient is
    available. Production code paths should read
    `engine_client.state.get("context_attachments")` or call
    `engine_client.get_context_attachments()` — those read from the
    canonical `AppState.context_attachments` field that every client
    (Rich, Textual, Web, VSCode) subscribes to. Maintaining two copies
    would invite drift; this function exists purely so unit tests can
    assert the scan logic without spinning up an engine.

    Walks `session.messages` and returns one entry per unique image-url part
    found anywhere in the conversation history, deduped by filename. Text
    attachments are not tracked — `build_multimodal_content` merges them
    into the prompt text at send time, leaving nothing distinguishable.

    Args:
        session: Any object exposing a `.messages` iterable of Message-like
                 records. A missing or non-iterable attribute yields [].

    Returns:
        List of ContextAttachment entries (possibly empty).
    """
    try:
        messages = getattr(session, "messages", None) or []
    except Exception:
        return []

    seen: set[str] = set()
    result: List[ContextAttachment] = []
    for msg in messages:
        content = getattr(msg, "content", None)
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") != "image_url":
                continue
            name = block.get("name") or "image"
            if name in seen:
                continue
            seen.add(name)
            result.append(ContextAttachment(name=name, kind="image"))
    return result


def build_multimodal_content(
    text: str,
    pending: List[PendingFile],
    *,
    model: str = "",
    provider: str = "",
    file_store: Any = None,
    vl_captioner: Any = None,
) -> List[Dict[str, Any]]:
    """Assemble OpenAI-format multimodal content from text + staged files.

    v1.17.4 Phase 2.2: delegates to `engine.file_preprocessing.preprocess_file`
    for per-file routing so `/attach` and the server chat route share the
    same pipeline (format validation, vision-vs-caption routing, store
    persistence, token cost estimation). `build_multimodal_content` is
    now a thin adapter that:

    1. Calls `preprocess_file` for each PendingFile with the live model
       + provider. This is where the vision-capable vs text-only routing
       decision happens — deliberately at send time, not attach time,
       so a user who `/attach`es then `/model`-switches still gets
       correct routing for whichever model is active when they send.

    2. Merges all `text` content parts (user prompt + text-file inlines
       + image captions + document references) into a single text part.
       Providers treat one big text block more consistently than many
       small ones, and some provider SDKs collapse adjacent text parts
       anyway.

    3. Appends `image_url` parts (or any other non-text kind) as
       separate content blocks following the merged text.

    Returns a list of content parts ready to pass to `EngineClient.chat()`.
    """
    text_chunks: List[str] = [text] if text else []
    non_text_parts: List[Dict[str, Any]] = []

    for pf in pending:
        result = preprocess_file(
            pf.name,
            pf.data,
            model=model,
            provider=provider or None,
            media_type=pf.media_type,
            file_store=file_store,
            vl_captioner=vl_captioner,
        )
        if not result.ok:
            # Surface the validation failure as a text annotation rather
            # than silently dropping the attachment. The user sees the
            # error inline in the prompt, the model sees it as part of
            # the context (useful for "what went wrong with my file?"
            # follow-ups).
            text_chunks.append(f"[Attachment error: {pf.name} — {result.error}]")
            continue

        for part in result.parts:
            if part.get("type") == "text":
                text_chunks.append(part["text"])
            else:
                non_text_parts.append(part)

    combined_text = "\n".join(chunk for chunk in text_chunks if chunk)

    parts: List[Dict[str, Any]] = []
    if combined_text:
        parts.append({"type": "text", "text": combined_text})
    parts.extend(non_text_parts)

    # Guarantee at least one part — providers reject empty messages.
    if not parts:
        parts.append({"type": "text", "text": ""})
    return parts


# =============================================================================
# Command Registration
# =============================================================================

CommandFactory.register(CommandSpec(
    name="attach",
    description="Stage files (images, text) for the next chat message",
    handler=handle_attach,
    category="utility",
    usage="/attach <path> [path2] ... | /attach | /attach clear",
    aliases=["att"],
))
