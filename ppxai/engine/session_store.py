"""
SessionFileStore — per-session binary file storage for multimodal attachments.

Phase 2.1 (v1.17.4). The keystone of the file-upload work: every downstream
step (preprocessing, PDF/Excel/PPTX tools, server chat route, client chips)
addresses files by a stable `file_id` resolved through this store, rather
than inlining base64 into message content or session JSON.

Design goals:

1. **Content-addressable IDs.** Each file's `file_id` is derived from a
   SHA-256 of its bytes plus a sanitized name hint. Two identical uploads
   within a session share an ID (free dedup), and the ID survives session
   save → load round trips because it's deterministic.

2. **Two-stage lifecycle.** Files live in a per-user staging directory
   (`~/.ppxai/uploads/<file_id>/<name>`) between `/attach` and session
   save, then get relocated into a session-local uploads directory
   (`~/.ppxai/sessions/<session_name>/uploads/<file_id>/<name>`) when the
   session is persisted. Session load restores from that directory.

3. **Message content carries file_id references, not bytes.** Once this
   module is wired into the engine (Phase 2.1a), `_serialize_message`
   rewrites `data:` URIs in `image_url` parts to compact `file_id`
   references, and `_deserialize_message` expands them back for in-memory
   operations. Session JSON stays tiny even with big images.

4. **Engine-owned, client-agnostic.** All clients (Rich / Textual / Web /
   VSCode) eventually read attachment metadata via
   `EngineClient.state.get("context_attachments")`, which is refreshed
   from this store. Clients never call `SessionFileStore` directly — they
   go through AppState (the pattern established in Phase 1 follow-up).

5. **Standalone-testable.** This module has zero imports from other
   engine layers. Tests exercise it in isolation with `tmp_path` fixtures
   before engine integration lands in 2.1a.
"""

from __future__ import annotations

import hashlib
import mimetypes
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

from ..common.logger import get_logger

logger = get_logger("session_store")


# Default staging directory for files before they are bound to a saved
# session. Overridable via constructor injection for tests.
_DEFAULT_STAGING_DIR = Path.home() / ".ppxai" / "uploads"


# Kind classification — broad categories used by status-bar badges and
# client chip components. Deliberately coarse; tools that need finer
# distinctions read the full `media_type` field directly.
KIND_IMAGE = "image"
KIND_TEXT = "text"
KIND_PDF = "pdf"
KIND_OFFICE = "office"
KIND_OTHER = "other"

_TEXT_EXTS = frozenset({
    ".py", ".js", ".ts", ".tsx", ".jsx", ".go", ".rs", ".c", ".cpp",
    ".h", ".hpp", ".java", ".kt", ".swift", ".rb", ".sh", ".zsh",
    ".bash", ".ps1", ".lua", ".sql", ".toml", ".yaml", ".yml",
    ".json", ".xml", ".ini", ".cfg", ".conf", ".env", ".tf",
    ".tfvars", ".hcl", ".md", ".markdown", ".rst", ".txt",
})

_OFFICE_MIME_TYPES = frozenset({
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/msword",
    "application/vnd.ms-excel",
    "application/vnd.ms-powerpoint",
})

_OFFICE_EXTS = frozenset({
    ".xlsx", ".xls", ".pptx", ".ppt", ".docx", ".doc",
})


@dataclass
class FileMetadata:
    """Metadata for a file tracked by SessionFileStore.

    Plain dataclass — all fields are JSON-serializable primitives plus a
    `Path`. Clients consume a dict projection of this struct (see
    `to_dict()`) via AppState, never the dataclass directly, to keep the
    Python → JS/TS schema mirror clean.

    Attributes:
        file_id: Stable content-addressed identifier
        name: Original filename (basename only; any leading dirs stripped)
        media_type: MIME type (e.g. "image/png")
        size: File size in bytes
        kind: Broad category ("image" | "text" | "pdf" | "office" | "other")
        path: Absolute on-disk path
    """
    file_id: str
    name: str
    media_type: str
    size: int
    kind: str
    path: Path

    def to_dict(self) -> Dict[str, object]:
        """JSON-serializable projection for AppState / SSE state_sync.

        Excludes `path` because it is a per-process absolute path that
        has no meaning to remote clients. Clients that need the raw bytes
        fetch them via a server endpoint keyed on `file_id`.
        """
        return {
            "file_id": self.file_id,
            "name": self.name,
            "media_type": self.media_type,
            "size": self.size,
            "kind": self.kind,
        }


class SessionFileStore:
    """Per-session binary file store for multimodal attachments.

    Lifecycle:
        # 1. User attaches a file via /attach or drag-drop.
        store = SessionFileStore()
        meta = store.save("chart.png", png_bytes)
        # meta.file_id is now stable; message content refers to it by id.

        # 2. Tool or server reads the file back later.
        path = store.get(meta.file_id)  # → Path on disk

        # 3. Session is saved — files relocate into the session dir.
        rel_map = store.move_to_session(Path.home() / ".ppxai/sessions/foo")
        # rel_map: {"abc123_chart.png": "uploads/abc123_chart.png/chart.png"}

        # 4. Session is loaded on a new process — rebuild from disk.
        new_store = SessionFileStore()
        new_store.restore_from_session(Path.home() / ".ppxai/sessions/foo")
        # Store is now populated with the same file_ids as before.
    """

    def __init__(self, base_dir: Optional[Path] = None) -> None:
        """Initialize the store.

        Args:
            base_dir: Directory for staged files (pre-save). Defaults to
                      `~/.ppxai/uploads/`. Tests inject a tmp_path here
                      to avoid touching the real filesystem location.
        """
        self._base_dir = Path(base_dir) if base_dir else _DEFAULT_STAGING_DIR
        self._base_dir.mkdir(parents=True, exist_ok=True)
        self._metadata: Dict[str, FileMetadata] = {}
        # When non-None, new uploads land under this directory instead of
        # the staging base. Set by move_to_session / restore_from_session.
        self._session_dir: Optional[Path] = None

    # ------------------------------------------------------------------
    # Core storage operations
    # ------------------------------------------------------------------

    def save(
        self,
        name: str,
        data: bytes,
        media_type: Optional[str] = None,
    ) -> FileMetadata:
        """Persist bytes to the store and return metadata.

        Idempotent: calling twice with the same bytes returns the existing
        metadata without touching disk again, because the `file_id` is
        derived from a content hash.

        Args:
            name: Original filename. Only the basename is kept — any
                  directory components are stripped defensively to
                  prevent path traversal via crafted names.
            data: File bytes to persist.
            media_type: Optional MIME type override. Auto-detected from
                        `name`'s extension if not provided.

        Returns:
            FileMetadata pointing at the on-disk file.

        Raises:
            OSError: If the file cannot be written (disk full, permission
                     denied, etc.). Callers should wrap in try/except and
                     surface a user-friendly error — SessionFileStore
                     intentionally does not swallow these.
        """
        safe_name = Path(name).name or "file"
        if not media_type:
            guessed, _ = mimetypes.guess_type(safe_name)
            media_type = guessed or "application/octet-stream"

        file_id = _compute_file_id(data, safe_name)

        # Dedup: identical bytes within a session reuse the existing file.
        if file_id in self._metadata:
            logger.debug(f"SessionFileStore: dedup hit for {safe_name} ({file_id})")
            return self._metadata[file_id]

        target_root = self._session_dir if self._session_dir else self._base_dir
        file_dir = target_root / file_id
        file_dir.mkdir(parents=True, exist_ok=True)
        file_path = file_dir / safe_name
        file_path.write_bytes(data)

        metadata = FileMetadata(
            file_id=file_id,
            name=safe_name,
            media_type=media_type,
            size=len(data),
            kind=classify_kind(media_type, safe_name),
            path=file_path,
        )
        self._metadata[file_id] = metadata
        logger.debug(
            f"SessionFileStore: saved {safe_name} ({len(data)} bytes) as {file_id}"
        )
        return metadata

    def get(self, file_id: str) -> Optional[Path]:
        """Return the on-disk path for a file_id, or None if unknown.

        Used by tools (e.g. `ReadPdfTool`, `GetPdfPageImageTool`) that
        need the raw bytes. Never dereferences the path — callers are
        responsible for reading the file.
        """
        meta = self._metadata.get(file_id)
        return meta.path if meta else None

    def get_metadata(self, file_id: str) -> Optional[FileMetadata]:
        """Return full metadata for a file_id, or None if unknown.

        Preferred over `get()` when callers need size/name/kind info
        for display (badges, chips, previews). Avoids an extra
        `os.stat()` round trip.
        """
        return self._metadata.get(file_id)

    def list_all(self) -> List[FileMetadata]:
        """Return all currently-tracked metadata entries.

        Used by `EngineClient._refresh_context_attachments()` after
        Phase 2.1a wiring: iterates this list to build the
        `context_attachments` AppState field.
        """
        return list(self._metadata.values())

    # ------------------------------------------------------------------
    # Lifecycle / cleanup
    # ------------------------------------------------------------------

    def cleanup(self, file_id: str) -> bool:
        """Remove a single file from the store.

        Deletes the on-disk bytes and evicts the metadata entry. The
        enclosing `file_id` directory is removed if it becomes empty.

        Returns True if the file was found and removed, False otherwise.
        Safe to call on unknown IDs (returns False without raising).
        """
        meta = self._metadata.pop(file_id, None)
        if not meta:
            return False
        try:
            if meta.path.exists():
                meta.path.unlink()
            parent = meta.path.parent
            # Only remove the parent if it's the file_id dir and it's empty.
            # Defensive: never rm -rf a directory we don't own.
            if (
                parent.exists()
                and parent.name == file_id
                and not any(parent.iterdir())
            ):
                parent.rmdir()
        except OSError as exc:
            logger.warning(
                f"SessionFileStore.cleanup({file_id}) failed: {exc}"
            )
        return True

    def cleanup_all(self) -> int:
        """Remove every file from the store and clear in-memory state.

        Called when starting a fresh session or when an `EngineClient`
        instance is torn down. Returns the number of files removed.
        """
        count = len(self._metadata)
        for file_id in list(self._metadata.keys()):
            self.cleanup(file_id)
        return count

    def reset(self) -> None:
        """Drop all in-memory file metadata so previously-tracked file_ids
        stop resolving — WITHOUT deleting on-disk bytes (use cleanup_all for
        that). Called by `SessionManager.load()` so loading a text-only / flat
        session doesn't leave the prior session's attachments accessible via
        `/files/serve/{id}` and `/files/preview/{id}` (security: finding #2)."""
        self._metadata.clear()

    # ------------------------------------------------------------------
    # Session binding — move staged files into / out of a session dir
    # ------------------------------------------------------------------

    def move_to_session(self, session_dir: Path) -> Dict[str, str]:
        """Relocate all staged files into a session's `uploads/` directory.

        Called by `SessionManager.save()` when persisting a session that
        has attachments. Moves every tracked file from the staging root
        to `session_dir/uploads/<file_id>/<name>`, updates in-memory
        `path` pointers, and returns a mapping suitable for session
        serialization to rewrite inline `data:` URIs into `file_id`
        references.

        Idempotent: files already under `session_dir/uploads` are left
        in place. Safe to call multiple times during a session that
        auto-saves.

        Args:
            session_dir: Target session directory.

        Returns:
            Mapping of `file_id` → relative path under session_dir
            (e.g. `"abc123_chart.png" → "uploads/abc123_chart.png/chart.png"`).
        """
        session_dir = Path(session_dir)
        uploads_root = session_dir / "uploads"
        uploads_root.mkdir(parents=True, exist_ok=True)

        rel_map: Dict[str, str] = {}
        for file_id, meta in list(self._metadata.items()):
            src = meta.path
            dst_dir = uploads_root / file_id
            dst_dir.mkdir(parents=True, exist_ok=True)
            dst = dst_dir / meta.name

            try:
                already_there = src.resolve() == dst.resolve()
            except OSError:
                already_there = False

            if already_there:
                rel_map[file_id] = f"uploads/{file_id}/{meta.name}"
                continue

            try:
                if src.exists():
                    shutil.move(str(src), str(dst))
                else:
                    # Source vanished (manual filesystem edit). Drop the
                    # tracked entry rather than claiming success.
                    logger.warning(
                        f"SessionFileStore.move_to_session: source missing "
                        f"for {file_id} at {src}, dropping entry"
                    )
                    self._metadata.pop(file_id, None)
                    continue

                meta.path = dst
                # Best-effort cleanup of the now-empty staging dir.
                try:
                    src.parent.rmdir()
                except OSError:
                    pass
                rel_map[file_id] = f"uploads/{file_id}/{meta.name}"
            except OSError as exc:
                logger.warning(
                    f"SessionFileStore.move_to_session({file_id}) failed: {exc}"
                )

        self._session_dir = uploads_root
        return rel_map

    def restore_from_session(self, session_dir: Path) -> int:
        """Rebuild in-memory state from an on-disk session directory.

        Called by `SessionManager.load()` during session restore. Scans
        `session_dir/uploads/<file_id>/<name>` entries, reconstructs
        metadata for each, and clears any previous in-memory state so
        the store reflects the loaded session exactly.

        Args:
            session_dir: Session directory to scan.

        Returns:
            Number of files successfully restored. Returns 0 silently
            if the session has no `uploads/` subdirectory (legacy
            text-only sessions or never-attached sessions).
        """
        session_dir = Path(session_dir)
        uploads_root = session_dir / "uploads"

        # Loading a session replaces the store wholesale — clear FIRST so a
        # directory session with no uploads/ still resets the prior session's
        # metadata (finding #2), not just after the early return below.
        self._metadata.clear()
        if not uploads_root.is_dir():
            return 0

        count = 0
        for file_id_dir in sorted(uploads_root.iterdir()):
            if not file_id_dir.is_dir():
                continue
            # Expect exactly one file per file_id directory. If there are
            # multiple (shouldn't happen, but be defensive), pick the
            # largest as the canonical one and log a warning.
            files = [p for p in file_id_dir.iterdir() if p.is_file()]
            if not files:
                continue
            if len(files) > 1:
                logger.warning(
                    f"SessionFileStore.restore_from_session: {file_id_dir.name} "
                    f"has {len(files)} files, expected 1 — using largest"
                )
                files.sort(key=lambda p: p.stat().st_size, reverse=True)
            file_path = files[0]

            try:
                size = file_path.stat().st_size
            except OSError as exc:
                logger.warning(
                    f"SessionFileStore.restore_from_session: stat failed "
                    f"for {file_path}: {exc}"
                )
                continue

            guessed, _ = mimetypes.guess_type(file_path.name)
            media_type = guessed or "application/octet-stream"

            self._metadata[file_id_dir.name] = FileMetadata(
                file_id=file_id_dir.name,
                name=file_path.name,
                media_type=media_type,
                size=size,
                kind=classify_kind(media_type, file_path.name),
                path=file_path,
            )
            count += 1

        self._session_dir = uploads_root
        return count


# =============================================================================
# Helpers (module-level so tests can exercise classification in isolation)
# =============================================================================


def classify_kind(media_type: str, name: str) -> str:
    """Classify a file into a broad kind for status-bar badges.

    Returns one of the KIND_* constants. MIME type is checked first
    because it's more reliable; extension is a fallback for text/code
    files where mimetypes.guess_type returns application/octet-stream.
    """
    if media_type.startswith("image/"):
        return KIND_IMAGE
    if media_type == "application/pdf":
        return KIND_PDF
    if media_type in _OFFICE_MIME_TYPES:
        return KIND_OFFICE
    if media_type.startswith("text/"):
        return KIND_TEXT

    # Extension-based fallbacks.
    suffix = Path(name).suffix.lower()
    if suffix in _OFFICE_EXTS:
        return KIND_OFFICE
    if suffix in _TEXT_EXTS:
        return KIND_TEXT
    if suffix == ".pdf":
        return KIND_PDF

    return KIND_OTHER


def _compute_file_id(data: bytes, name: str) -> str:
    """Compute a stable file_id from content + name hint.

    The hash dominates (16 hex chars of SHA-256 → 2^64 collision space,
    far more than enough for a single user's session) and the name hint
    is appended purely for human debuggability when inspecting the
    staging directory — it has no role in identity resolution.

    Name hints are truncated and sanitized so a pathological filename
    can't blow up the directory layer or inject path separators.
    """
    digest = hashlib.sha256(data).hexdigest()[:16]
    # Sanitize name hint: keep alphanumerics, dots, dashes, underscores.
    # Everything else collapses to underscore. Prevents crafted names
    # from leaking directory separators into the file_id.
    safe_chars = []
    for ch in name:
        if ch.isalnum() or ch in (".", "-", "_"):
            safe_chars.append(ch)
        else:
            safe_chars.append("_")
    name_hint = "".join(safe_chars)[:32] or "file"
    return f"{digest}_{name_hint}"


__all__ = [
    "SessionFileStore",
    "FileMetadata",
    "classify_kind",
    "KIND_IMAGE",
    "KIND_TEXT",
    "KIND_PDF",
    "KIND_OFFICE",
    "KIND_OTHER",
]
