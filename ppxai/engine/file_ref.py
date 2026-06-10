"""Unified file-reference resolution for office-format tools.

v1.18.7: office tools (pdf/pptx/excel/docx) historically only accepted
`file_id` from SessionFileStore. With the workspace upload + file-tree
features landed in v1.18.7, files often live at a workspace path with
no SessionFileStore entry, and the model has no way to address them
through native tools — it falls back to shell+python.

This module exposes one resolver that accepts EITHER `file_id` OR
`path`, returning a uniform `(meta, error)` tuple. The two namespaces
have distinct semantics that callers should preserve:

- file_id  → SessionFileStore: per-session, revived from cache on
  session reload, attached to the conversation checkpoint
- path     → workspace: workspace-wide, addressable from any session,
  the appropriate reference for AGENTS.md / docs

Resolution rules:
- Exactly one of file_id/path must be provided
- file_id: SessionFileStore lookup (unchanged behavior)
- path: resolved relative to engine.get_working_dir(); absolute paths
  must be inside working_dir (no escapes); media_type guessed from
  extension
"""

from __future__ import annotations

import mimetypes
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Tuple


@dataclass
class FileRef:
    """Subset of SessionFileStore.FileMetadata used by office tools.

    Field names match FileMetadata so consumers don't need to branch on
    the concrete type — both the SessionFileStore entry and this stub
    expose `.name`, `.media_type`, `.path`.
    """
    name: str
    media_type: str
    path: Path


_OFFICE_MIME_BY_EXT = {
    ".pdf": "application/pdf",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".ppt": "application/vnd.ms-powerpoint",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".xls": "application/vnd.ms-excel",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".doc": "application/msword",
    ".csv": "text/csv",
}


def _guess_media_type(path: Path) -> str:
    ext = path.suffix.lower()
    if ext in _OFFICE_MIME_BY_EXT:
        return _OFFICE_MIME_BY_EXT[ext]
    guessed, _ = mimetypes.guess_type(str(path))
    return guessed or "application/octet-stream"


def resolve_file_reference(
    engine: Any,
    file_id: Optional[str] = None,
    path: Optional[str] = None,
) -> Tuple[Optional[Any], Optional[str]]:
    """Resolve a file reference from either file_id or workspace path.

    Returns (meta, error). meta is either a SessionFileStore.FileMetadata
    or a FileRef stub — both expose `name`, `media_type`, `path`.

    Args:
        engine: Engine instance (must expose `file_store` for file_id
            branch and `get_working_dir()` for path branch).
        file_id: SessionFileStore content-addressed identifier.
        path: Workspace-relative or absolute path. Absolute paths must
            resolve INSIDE the engine's working_dir (security: prevents
            reading arbitrary host files).

    Returns:
        (meta, None) on success; (None, error_message) on failure.
        Errors are user-facing strings safe to surface to the model.
    """
    if file_id and path:
        return None, "Pass either 'file_id' or 'path', not both."
    if not file_id and not path:
        return None, "Must pass either 'file_id' (chat attachment) or 'path' (workspace file)."

    if file_id:
        file_store = getattr(engine, "file_store", None)
        if file_store is None:
            return None, "No SessionFileStore available; use 'path' for workspace files."
        meta = file_store.get_metadata(file_id)
        if meta is None:
            return None, f"Unknown file_id: {file_id!r}. The attachment may have been removed."
        if not meta.path.exists():
            return None, f"File for {file_id!r} is missing on disk."
        return meta, None

    # path branch
    p = Path(path).expanduser()
    working_dir: Optional[Path] = None
    get_wd = getattr(engine, "get_working_dir", None)
    if callable(get_wd):
        wd = get_wd()
        if wd:
            working_dir = Path(wd).resolve()

    if not p.is_absolute():
        if working_dir is None:
            return None, "Cannot resolve relative path: engine has no working_dir."
        p = (working_dir / p).resolve()
    else:
        p = p.resolve()

    if working_dir is not None:
        try:
            p.relative_to(working_dir)
        except ValueError:
            return None, (
                f"Path {str(p)!r} is outside the working directory {str(working_dir)!r}. "
                "Office tools refuse to read files outside the workspace."
            )

    if not p.exists():
        return None, f"Path does not exist: {str(p)!r}"
    if not p.is_file():
        return None, f"Path is not a regular file: {str(p)!r}"

    return FileRef(name=p.name, media_type=_guess_media_type(p), path=p), None


# Reusable JSON-Schema fragment for office-tool parameters. Each tool's
# `self.parameters` merges this in. "required" stays empty because
# exactly-one-of validation happens at execute() time (JSON Schema's
# oneOf/anyOf is poorly supported by many tool-calling models).
FILE_REF_PROPERTIES = {
    "file_id": {
        "type": "string",
        "description": (
            "Content-addressed id for a file attached to this chat session "
            "(SessionFileStore). Use for chat-uploaded files revived from "
            "the session cache. Pass exactly one of file_id or path."
        ),
    },
    "path": {
        "type": "string",
        "description": (
            "Workspace-relative or absolute path to a workspace file (visible "
            "in the file tree, addressable from any session). Use for work "
            "material like project files. Pass exactly one of file_id or path."
        ),
    },
}
