"""
File operations endpoints (search, list, tree, read, write, image).
"""

import asyncio
import base64
import hashlib
import os
import sys
import time
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response

from ...common.docx_to_pdf import convert_docx_to_pdf
from ...common.logger import get_logger
from ...config import get_file_tree_ignore_dirs
from ...engine.tools.builtin.docx_tools import _extract_docx_text
from ..models import FileReadRequest, FileSearchRequest, FileWriteRequest
from ..state import (
    MIME_TYPES,
    Session,
    get_session,
    get_session_or_query,
    is_path_allowed,
    with_drained_events,
)

logger = get_logger("server")

# v1.18.7: promoted to config — `file_tree.ignore_dirs` in ppxai-config.json
# (default list still {.git, node_modules, __pycache__, .venv, venv, .tox,
# dist, build, .eggs, .mypy_cache} via DEFAULT_FILE_TREE_IGNORE_DIRS). Read
# via get_file_tree_ignore_dirs() at request time so config changes take
# effect without server restart. The four call sites below all use the
# function, NOT a cached module-level constant.

# v1.18.7: path-derived cache for /files/preview (path-based variant).
# Each unique path gets its own subdir keyed by sha256, so re-rendering
# the same file is free across server restarts. Lives at
# ~/.ppxai/.preview-cache/<sha256-prefix>/ in parallel to the file_store-
# backed cache at meta.path.parent / "slides" that the existing
# /files/preview/{file_id} uses. Separating them avoids collision
# between attached-file previews and browse-only previews.
_PREVIEW_CACHE_ROOT = Path.home() / ".ppxai" / ".preview-cache"


def _path_cache_dir(path: Path) -> Path:
    """Per-file cache dir for path-based preview rendering.

    Uses the first 16 hex chars of sha256(absolute_path) as the dir
    name — collision-resistant for any realistic file count, short
    enough that the cache root stays browseable in a file manager.
    """
    digest = hashlib.sha256(str(path.resolve()).encode("utf-8")).hexdigest()[:16]
    return _PREVIEW_CACHE_ROOT / digest


router = APIRouter()


# ---------------------------------------------------------------------------
# cwd_anchor mismatch handling (v1.18.1 state-sync Phase D)
# ---------------------------------------------------------------------------

def _check_cwd_anchor(
    cwd_anchor: str | None,
    engine_working_dir: str,
    engine_for_drain,
) -> None:
    """Raise HTTPException(409) when the client's anchor doesn't
    match the engine's current working_dir.

    The 409 body carries:
      - detail   : human-readable summary
      - expected : the cwd the client thought it was anchored to
      - actual   : the engine's current cwd
      - events   : drained side-channel events so the client can
                   re-anchor AppState before retrying

    No-op when cwd_anchor is None — backward-compatible for clients
    that haven't been updated to send the anchor yet.

    Path comparison is normalised via Path().resolve() so trailing
    slashes / different separators / `..` segments don't cause
    false-positive conflicts.
    """
    if cwd_anchor is None:
        return
    try:
        anchor = str(Path(cwd_anchor).resolve())
        actual = str(Path(engine_working_dir).resolve())
    except OSError:
        # Path resolution can fail on weird inputs (network paths,
        # malformed strings) — treat as mismatch so the client
        # retries with a fresh anchor instead of 500'ing.
        anchor = cwd_anchor
        actual = engine_working_dir
    if anchor == actual:
        return
    body = with_drained_events(
        {
            "detail": "working directory drift",
            "expected": anchor,
            "actual": actual,
        },
        engine_for_drain,
    )
    raise HTTPException(status_code=409, detail=body)


# ---------------------------------------------------------------------------
# Shared path resolution + security check (v1.18.7)
# ---------------------------------------------------------------------------
#
# /files/read, /files/preview (path-based), and /files/download all need
# the same "resolve relpath against working_dir, expand ~, expand @search,
# enforce working_dir-or-home-dir scope" logic. Extracted here so the
# three endpoints share one definition + one security review.

# File extensions where /files/read returns base64-encoded binary bytes
# (the legacy image+pdf set plus office spreadsheets that the web client
# renders inline via SheetJS without server-side conversion). Tracks
# state.MIME_TYPES — anything in MIME_TYPES that isn't text/* should
# also appear here. Office presentations + Word docs go through the
# path-based /files/preview endpoint instead (LibreOffice conversion).
BINARY_PREVIEW_EXTENSIONS = {
    # Images
    '.png', '.jpg', '.jpeg', '.gif', '.webp', '.svg', '.bmp', '.ico',
    # PDF
    '.pdf',
    # Spreadsheets (rendered client-side via SheetJS)
    '.xlsx', '.xls', '.csv',
}

# Office types where /files/preview (path-based) does server-side
# conversion via LibreOffice (with text-extraction fallback when
# LibreOffice is missing).
OFFICE_PREVIEWABLE_EXTENSIONS = {
    '.pptx', '.ppt', '.docx', '.doc',
}


def _within_tree(path: Path, base: Path) -> bool:
    """True iff `path` is `base` itself or sits inside `base`'s subtree.

    Both arguments must already be `.resolve()`d. This compares path
    *components*, so unlike a `str(path).startswith(str(base))` prefix
    test it does NOT treat ``/home/userEVIL`` as inside ``/home/user``.
    Unlike `is_path_allowed`, it is one-directional (child-only): an
    ancestor of `base` does not pass.
    """
    return path == base or base in path.parents


def _resolve_safe_path(
    raw: str,
    engine,
    cwd_anchor: str | None = None,
    allow_directory: bool = False,
) -> Path:
    """Resolve user-supplied path to an absolute, access-allowed Path.

    Handles the three input flavors `/files/read` historically accepted:
    - `@search-query` — fuzzy search in working_dir, returns first match
    - `~/relpath` — tilde expansion to user home
    - bare relpath or absolute path — resolved against working_dir if relative

    Security: resolves the path with `.resolve()` (path traversal-safe),
    then asserts it sits inside the working_dir tree OR the user's home
    directory tree. Raises HTTPException 403 / 404 on failure with the
    same status codes the legacy in-line code raised, so callers don't
    need to translate.

    Also handles cwd_anchor verification for relative-path callers,
    raising 409 if the engine's cwd has drifted (matches the legacy
    behavior at files.py:448-455).

    Args:
        raw: Raw path string from the request body / query string.
        engine: EngineClient (needed for cwd + drain-on-409).
        cwd_anchor: Client's cwd at click time, for drift detection on
            relative paths. None disables the check.

    Returns:
        Resolved absolute Path that has passed the security check.

    Raises:
        HTTPException 400: path is empty / not a file (caller may want
            to differentiate; we always raise 400 for malformed input).
        HTTPException 403: resolved path outside working_dir + home_dir trees.
        HTTPException 404: file does not exist (or @search has no match).
        HTTPException 409: cwd_anchor doesn't match engine.get_working_dir().
    """
    filepath = (raw or "").strip()
    if not filepath:
        raise HTTPException(status_code=400, detail="Empty path")

    # Phase D: cwd_anchor check for relative paths (skip for @ + ~ + absolute).
    if not filepath.startswith('@') and not filepath.startswith('~'):
        if not Path(filepath).is_absolute():
            _check_cwd_anchor(
                cwd_anchor,
                engine.get_working_dir() or os.getcwd(),
                engine,
            )

    # @search-query — fuzzy filename match against working_dir.
    if filepath.startswith('@'):
        query = filepath[1:]
        working_dir = Path(engine.get_working_dir() or os.getcwd())
        try:
            for candidate in working_dir.rglob('*'):
                try:
                    if candidate.is_file() and query.lower() in candidate.name.lower():
                        filepath = str(candidate)
                        break
                except OSError:
                    continue
            else:
                raise HTTPException(
                    status_code=404,
                    detail=f"No files found matching: {query}",
                )
        except (PermissionError, OSError):
            raise HTTPException(
                status_code=404,
                detail=f"No files found matching: {query}",
            )

    # Tilde expansion.
    if filepath.startswith('~'):
        filepath = os.path.expanduser(filepath)

    path = Path(filepath)
    if not path.is_absolute():
        path = Path(engine.get_working_dir() or os.getcwd()) / filepath

    path = path.resolve()

    # Security: working_dir tree OR home_dir tree. The home check is a
    # component-wise subtree test (_within_tree), not a string prefix, so a
    # sibling like `/home/userEVIL` cannot pass as inside `/home/user`.
    working_dir = Path(engine.get_working_dir() or os.getcwd()).resolve()
    home_dir = Path.home().resolve()
    if not (is_path_allowed(path, working_dir) or _within_tree(path, home_dir)):
        logger.warning(
            f"  Access denied: {path} not in {working_dir} tree or {home_dir}"
        )
        raise HTTPException(
            status_code=403,
            detail="Access denied: path outside allowed directories",
        )

    if not path.exists():
        raise HTTPException(
            status_code=404,
            detail=f"File not found: {raw} (resolved: {path})",
        )

    # v1.18.7: opt-in directory targets for callers like /files/upload
    # whose destination is a folder, not a file. read/preview/download
    # still default to is_file() because rendering a directory makes no
    # sense for them.
    if allow_directory:
        if not (path.is_file() or path.is_dir()):
            raise HTTPException(
                status_code=400,
                detail=f"Not a file or directory: {raw}",
            )
    else:
        if not path.is_file():
            raise HTTPException(status_code=400, detail=f"Not a file: {raw}")

    return path


@router.post("/files/search")
async def search_files(
    request: FileSearchRequest,
    s: Session = Depends(get_session)
):
    """Search for files in working directory (v1.13.8 - for @file autocomplete).

    Searches files recursively in the working directory, filtering by query.
    Returns list of matching files with relative paths.

    Args:
        request: FileSearchRequest with query and max_results

    Returns:
        JSON: {"files": [{"name": "file.py", "path": "src/file.py"}, ...]}
    """

    logger.info(f"HTTP POST /files/search - query: {request.query}")

    working_dir = Path(s.engine.get_working_dir() or os.getcwd())
    query = request.query.lower()
    results = []
    ignore_dirs = get_file_tree_ignore_dirs()  # v1.18.7: read once per request

    try:
        for path in working_dir.rglob('*'):
            if len(results) >= request.max_results:
                break
            try:
                # Check if file - can fail on network paths (WinError 4350)
                if path.is_file():
                    # Skip files in ignored directories
                    if any(ignored in path.parts for ignored in ignore_dirs):
                        continue
                    try:
                        rel_path = str(path.relative_to(working_dir))
                        filename = path.name
                        # Match query against filename or path
                        if not query or query in filename.lower() or query in rel_path.lower():
                            results.append({
                                "name": filename,
                                "path": rel_path
                            })
                    except ValueError:
                        pass
            except OSError:
                # Network file unavailable, skip it
                pass
    except (PermissionError, OSError):
        pass

    # Also add special @ references
    special_refs = [
        {"name": "@git", "path": "Include git diff"},
        {"name": "@tree", "path": "Include project structure"},
    ]

    # Filter special refs by query
    if query:
        special_refs = [ref for ref in special_refs if query in ref["name"].lower()]

    return {"files": special_refs + results}


@router.get("/files/list")
async def list_files(
    path: str | None = None,
    a: bool = False,
    s: Session = Depends(get_session)
):
    """List directory contents (v1.16.0 - for /ls command).

    Returns files and directories with metadata, sorted dirs-first then alphabetical.

    Args:
        path: Optional subpath relative to working directory
        a: Include hidden files

    Returns:
        JSON: {"files": [...], "path": "/abs/path"}
    """

    working_dir = Path(s.engine.get_working_dir() or os.getcwd())
    if path:
        path_obj = Path(path).expanduser()
        target = path_obj if path_obj.is_absolute() else working_dir / path_obj
    else:
        target = working_dir
    target = target.resolve()

    logger.info(f"HTTP GET /files/list - path: {target}")

    if not target.is_dir():
        raise HTTPException(status_code=404, detail=f"Not a directory: {path or '.'}")

    try:
        entries = list(target.iterdir())
    except PermissionError:
        raise HTTPException(status_code=403, detail="Permission denied")

    ignore_dirs = get_file_tree_ignore_dirs()  # v1.18.7
    filtered = []
    for entry in entries:
        name = entry.name
        if not a and name.startswith('.'):
            continue
        if entry.is_dir() and name in ignore_dirs:
            continue
        filtered.append(entry)

    filtered.sort(key=lambda e: (not e.is_dir(), e.name.lower()))

    files = []
    for entry in filtered:
        is_dir = entry.is_dir()
        try:
            stat = entry.stat()
            files.append({
                "name": entry.name + ('/' if is_dir else ''),
                "size": stat.st_size if not is_dir else None,
                "modified": time.strftime('%Y-%m-%dT%H:%M:%S', time.localtime(stat.st_mtime)),
                "is_dir": is_dir
            })
        except OSError:
            files.append({
                "name": entry.name + ('/' if is_dir else ''),
                "size": None,
                "modified": None,
                "is_dir": is_dir
            })

    at_fs_root = target.parent == target  # True when cwd is filesystem root (e.g. /)
    # v1.18.1 Phase D: include `working_dir` so clients can store
    # it as a `cwd_anchor` and detect drift when they later issue
    # /files/read against a relpath that no longer resolves.
    return {
        "files": files,
        "path": str(target),
        "at_fs_root": at_fs_root,
        "working_dir": str(working_dir.resolve()),
    }


@router.get("/files/tree")
async def get_file_tree(
    path: str | None = None,
    depth: int = 3,
    s: Session = Depends(get_session)
):
    """Get directory tree structure (v1.16.0 - for /tree command).

    Returns recursive tree of files and directories.

    Args:
        path: Optional subpath relative to working directory
        depth: Maximum depth (default 3, capped at 6)

    Returns:
        JSON: {"tree": {...}, "path": "/abs/path", "stats": {"dirs": N, "files": N}}
    """

    working_dir = Path(s.engine.get_working_dir() or os.getcwd())
    if path:
        path_obj = Path(path).expanduser()
        target = path_obj if path_obj.is_absolute() else working_dir / path_obj
    else:
        target = working_dir
    target = target.resolve()
    depth = min(depth, 6)

    logger.info(f"HTTP GET /files/tree - path: {target}, depth: {depth}")

    if not target.is_dir():
        raise HTTPException(status_code=404, detail=f"Not a directory: {path or '.'}")

    dir_count = 0
    file_count = 0
    ignore_dirs = get_file_tree_ignore_dirs()  # v1.18.7: resolved once per request

    def build_tree(directory: Path, current_depth: int) -> dict:
        nonlocal dir_count, file_count
        children = []
        if current_depth >= depth:
            return {"label": directory.name, "children": children}

        try:
            entries = sorted(directory.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower()))
        except PermissionError:
            return {"label": directory.name + " [permission denied]", "children": []}

        for entry in entries:
            name = entry.name
            if name.startswith('.'):
                continue
            if entry.is_dir():
                if name in ignore_dirs:
                    continue
                dir_count += 1
                children.append(build_tree(entry, current_depth + 1))
            else:
                file_count += 1
                children.append({"label": name, "children": []})

        return {"label": directory.name + "/", "children": children}

    # Offload the walk: build_tree is fully synchronous filesystem I/O, and a
    # large working_dir makes it long. Run on the event loop it stalls EVERY
    # other request for its whole duration -- a user whose working_dir is their
    # home directory freezes the server for every connected client, not just
    # the one that asked for the tree. Same rationale as the v1.19.0 provider-call
    # offload in oneshot.py / agent_v1.py.
    tree = await asyncio.to_thread(build_tree, target, 0)
    tree["label"] = str(target) + "/"

    return {
        "tree": tree,
        "path": str(target),
        "stats": {"dirs": dir_count, "files": file_count}
    }


@router.post("/files/write")
async def write_file(
    request: FileWriteRequest,
    s: Session = Depends(get_session)
):
    """Write file contents (v1.14.1 - for /edit command).

    Writes content to a file, creating it if it doesn't exist.
    Path validation ensures writes only to allowed directories.

    Args:
        request: FileWriteRequest with path and content

    Returns:
        JSON: {"path", "success", "created", "size"}

    v1.14.1: Added for VSCode /edit command.
    """

    logger.info(f"HTTP POST /files/write - path: {request.path}")

    filepath = request.path.strip()

    # Phase D: anchor check before any path resolution.
    if not filepath.startswith('~'):
        _path_obj = Path(filepath)
        if not _path_obj.is_absolute():
            _check_cwd_anchor(
                request.cwd_anchor,
                s.engine.get_working_dir() or os.getcwd(),
                s.engine,
            )

    # Resolve path - handle tilde expansion
    if filepath.startswith('~'):
        filepath = os.path.expanduser(filepath)

    path = Path(filepath)
    if not path.is_absolute():
        working_dir = Path(s.engine.get_working_dir() or os.getcwd())
        path = working_dir / filepath

    path = path.resolve()
    logger.debug(f"  Resolved path: {path}")

    # Security: ensure path is within working directory tree or home directory
    working_dir = Path(s.engine.get_working_dir() or os.getcwd()).resolve()
    home_dir = Path.home().resolve()

    # Allow files in working directory tree or home directory tree.
    # _within_tree is a component-wise subtree test, not a string prefix,
    # so `/home/userEVIL` cannot pass as inside `/home/user`.
    if not (is_path_allowed(path, working_dir) or _within_tree(path, home_dir)):
        logger.warning(f"  Access denied: {path} not in {working_dir} tree or {home_dir}")
        raise HTTPException(
            status_code=403, detail="Access denied: path outside allowed directories"
        )

    # Check if file exists (to report 'created' vs 'updated')
    created = not path.exists()

    # Ensure parent directory exists
    path.parent.mkdir(parents=True, exist_ok=True)

    try:
        path.write_text(request.content, encoding='utf-8')
        size = path.stat().st_size

        logger.info(f"  File {'created' if created else 'updated'}: {path} ({size} bytes)")

        return {
            "path": str(path),
            "success": True,
            "created": created,
            "size": size
        }
    except PermissionError:
        raise HTTPException(status_code=403, detail=f"Permission denied: {filepath}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error writing file: {str(e)}")


@router.get("/files/image/{filepath:path}")
async def serve_image(
    filepath: str,
    cwd_anchor: str | None = None,
    s: Session = Depends(get_session_or_query)
):
    """Serve raw image file for inline display in chat bubbles (v1.16.2).

    Returns the image binary with correct Content-Type header.
    Used by marked.js ![alt](/files/image/path) in chat messages.

    cwd_anchor query string (v1.18.1 Phase D): when the relpath
    was resolved client-side from a stale cwd, return 409 with the
    new cwd in the body so the client can refresh the markdown
    before showing a broken image.

    v1.18.1 hotfix: uses `get_session_or_query` so `<img>` tags can
    pass `?session=<id>` (browsers can't add custom headers on
    HTMl-attribute-driven fetches). Without it, the route fell back
    to the default session and returned 404 whenever the user's
    session cwd differed from the server-process cwd.
    """

    path = Path(filepath)
    # Phase D: relpath-only — absolute paths bypass cwd entirely.
    if not path.is_absolute():
        _check_cwd_anchor(
            cwd_anchor,
            s.engine.get_working_dir() or os.getcwd(),
            s.engine,
        )
        working_dir = Path(s.engine.get_working_dir() or os.getcwd())
        path = working_dir / filepath
    path = path.resolve()

    # Security: same checks as /files/read. The home check is a
    # component-wise subtree test (_within_tree), not a string prefix, so a
    # sibling like `/home/userEVIL` cannot pass as inside `/home/user`.
    working_dir = Path(s.engine.get_working_dir() or os.getcwd()).resolve()
    home_dir = Path.home().resolve()
    if not (is_path_allowed(path, working_dir) or _within_tree(path, home_dir)):
        raise HTTPException(status_code=403, detail="Access denied")

    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail=f"Not found: {filepath}")

    ext = path.suffix.lower()
    mime_type = MIME_TYPES.get(ext)
    if not mime_type or not mime_type.startswith('image/'):
        raise HTTPException(status_code=400, detail=f"Not an image: {filepath}")

    return FileResponse(path, media_type=mime_type)


def _classify_extension(ext: str) -> str:
    """Map file extension to the `type` field /files/read returns.

    Centralizes the binary-vs-text classification so callers don't
    each maintain their own extension table. Returns one of:
    - "image" — image/* mime types (rendered inline by browsers)
    - "pdf" — application/pdf (rendered via iframe)
    - "office_spreadsheet" — xlsx/xls/csv (client-side SheetJS render)
    - "text" — anything else, attempts UTF-8 decode at read time
    """
    image_extensions = {'.png', '.jpg', '.jpeg', '.gif', '.webp', '.svg', '.bmp', '.ico'}
    spreadsheet_extensions = {'.xlsx', '.xls', '.csv'}
    if ext in image_extensions:
        return "image"
    if ext == '.pdf':
        return "pdf"
    if ext in spreadsheet_extensions:
        return "office_spreadsheet"
    return "text"


@router.post("/files/read")
async def read_file(
    request: FileReadRequest,
    s: Session = Depends(get_session)
):
    """Read file contents (v1.13.1 - for /show command).

    Reads a file from the working directory or absolute path.
    Supports @search-query format for fuzzy file matching.

    v1.18.7: refactored to use the shared `_resolve_safe_path` helper
    (was inline path-resolution logic duplicated with /files/preview +
    /files/download). Binary-type dispatch now goes through
    `_classify_extension` and the BINARY_PREVIEW_EXTENSIONS set so
    new binary types (spreadsheets) reach the base64 branch
    automatically. PPTX + Word + other office types fall through to
    the text branch's UnicodeDecodeError 400 — clients should call
    /files/preview?path= for those instead.

    Args:
        request: FileReadRequest with path

    Returns:
        JSON: {"filename", "path", "type", "content", "size", "lines"?, "mime_type"?}

    v1.13.10: Supports X-Session-Id header for session isolation.
    """
    logger.info(f"HTTP POST /files/read - path: {request.path}")
    logger.debug(f"  Working directory: {s.engine.get_working_dir()}")

    path = _resolve_safe_path(request.path, s.engine, request.cwd_anchor)
    logger.debug(f"  Resolved path: {path}")

    working_dir = Path(s.engine.get_working_dir() or os.getcwd()).resolve()
    ext = path.suffix.lower()
    size = path.stat().st_size
    file_type = _classify_extension(ext)

    # Compute display filename — relative path from working_dir so
    # the web editor saves to the correct location (not just basename
    # in the working_dir root).
    try:
        rel_name = path.relative_to(working_dir).as_posix()
    except ValueError:
        rel_name = path.name

    if ext in BINARY_PREVIEW_EXTENSIONS:
        try:
            content_bytes = path.read_bytes()
            content_b64 = base64.b64encode(content_bytes).decode('ascii')
            mime_type = MIME_TYPES.get(ext, 'application/octet-stream')
            return {
                "filename": rel_name,
                "path": str(path),
                "type": file_type,
                "mime_type": mime_type,
                "content": content_b64,
                "size": size,
            }
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Error reading {file_type}: {str(e)}")

    try:
        content = path.read_text(encoding='utf-8')
        return {
            "filename": rel_name,
            "path": str(path),
            "type": "text",
            "content": content,
            "size": size,
            "lines": content.count('\n') + 1,
        }
    except UnicodeDecodeError:
        # Office presentations + Word docs hit this branch — they're
        # binary but aren't in BINARY_PREVIEW_EXTENSIONS (rendered via
        # /files/preview?path= server-side). Surface a hint to that
        # endpoint in the error detail so clients know where to route.
        if ext in OFFICE_PREVIEWABLE_EXTENSIONS:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Binary office file: {ext} preview goes through "
                    f"/files/preview?path= (LibreOffice or text-extraction "
                    f"fallback). /files/read returns text only."
                ),
            )
        raise HTTPException(status_code=400, detail="Cannot read binary file")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error reading file: {str(e)}")


# ---------------------------------------------------------------------------
# Path-based office preview (v1.18.7)
# ---------------------------------------------------------------------------
#
# Counterpart to /files/preview/{file_id} in file_serve.py: same renderer
# (LibreOffice via render_pptx_slides / convert_docx_to_pdf) but accepts
# a working-dir-relative or absolute path instead of a SessionFileStore
# file_id. Used by the file-tree click path for office docs — files
# browsed in the sidebar were never registered with the store, so the
# file_id route couldn't serve them.
#
# Cache lives separately at ~/.ppxai/.preview-cache/<sha256(path)>/ so
# browse-only previews don't pollute the attached-file cache and vice
# versa. Key separation: previewing != attaching to chat.
#
# LibreOffice-missing fallback: returns extracted text (via
# extract_pptx_slide_text / _extract_docx_text public helpers) as a
# JSON payload with `type: "text_fallback"`. Web client renders the
# text inline with a "install LibreOffice for raster preview" note.


# Legacy binary office formats python-pptx / python-docx cannot open —
# they need LibreOffice. Without it we return a typed text_fallback message
# instead of letting the OOXML-only libraries 500.
_LEGACY_OFFICE_EXTENSIONS = {'.ppt', '.doc'}


def _text_fallback(*, kind: str, name: str, total: int, content: str,
                   slide: int | None = None) -> JSONResponse:
    """The single text_fallback JSON shape (LibreOffice-missing degrade)."""
    body = {
        "type": "text_fallback",
        "kind": kind,
        "content": content,
        "name": name,
        "total": total,
        "libreoffice_available": False,
    }
    if slide is not None:
        body["slide"] = slide
    return JSONResponse(body)


def render_office_preview(
    file_path: Path,
    name: str,
    ext: str,
    cache_dir: Path,
    *,
    slide: int = 1,
    total: bool = False,
):
    """Unified office-doc preview renderer shared by BOTH `/files/preview`
    routes (path-based in this module, file_id-based in `file_serve.py`).

    ONE response contract regardless of caller (item 26):
      - total=True → JSONResponse
            {total, name, type, kind, libreoffice_available}  (all keys always present)
      - slide=N    → FileResponse: image/png (PPTX) | application/pdf (Word)
      - LibreOffice missing → **200** JSONResponse
            {type:"text_fallback", kind, content, name, total, libreoffice_available:false}

    Never 503 for missing LibreOffice; legacy `.ppt`/`.doc` without LibreOffice
    return a typed text_fallback message instead of a python-pptx/docx 500.

    Args:
        file_path: Real file to render (path-resolved or file_store meta.path).
        name: Display name (also the source of the office `type`/`kind`).
        ext: Authoritative office extension (callers derive it reliably —
             `meta.path` is content-addressed and may lack an extension).
        cache_dir: Where rendered PNG/PDF artifacts are cached.
    """
    ext = ext.lower()
    if ext not in OFFICE_PREVIEWABLE_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unsupported extension {ext!r} for /files/preview. "
                f"Supported: {sorted(OFFICE_PREVIEWABLE_EXTENSIONS)}. For "
                f"images/PDFs use /files/read; for spreadsheets the web "
                f"client uses /files/read with client-side SheetJS."
            ),
        )

    is_word = ext in {'.docx', '.doc'}
    is_legacy = ext in _LEGACY_OFFICE_EXTENSIONS

    from ...engine.tools.builtin.pptx_tools import _libreoffice_available
    libreoffice_ok = _libreoffice_available()

    # ── Word document path ───────────────────────────────────────────
    if is_word:
        if libreoffice_ok:
            try:
                pdf_path = convert_docx_to_pdf(file_path, cache_dir)
            except Exception as exc:
                raise HTTPException(status_code=500, detail=f"Conversion failed: {exc}")
            if total:
                return JSONResponse({
                    "total": 1, "name": name, "type": "pdf", "kind": "word",
                    "libreoffice_available": True,
                })
            # FileResponse sends Last-Modified/ETag from the cached PDF and
            # handles If-Modified-Since → 304; no-cache forces revalidation
            # each click so edits propagate instantly while the round-trip
            # stays cheap (304, no body).
            return FileResponse(
                pdf_path,
                media_type="application/pdf",
                headers={"Cache-Control": "private, no-cache"},
            )
        # LibreOffice missing — degrade to text (never 503 / 500).
        if is_legacy:
            return _text_fallback(
                kind="word", name=name, total=1,
                content=(f"Legacy binary `{ext}` preview needs LibreOffice "
                         f"(install it for a rendered preview). The model can "
                         f"still read the document via tools."),
            )
        try:
            text = _extract_docx_text(file_path)
        except Exception as exc:
            text = (f"(Could not extract text: {exc}. Install LibreOffice for "
                    f"a rendered preview.)")
        return _text_fallback(kind="word", name=name, total=1, content=text)

    # ── PPTX path ────────────────────────────────────────────────────
    if libreoffice_ok:
        from ...engine.tools.builtin.pptx_tools import render_pptx_slides
        try:
            pngs = render_pptx_slides(file_path, cache_dir)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Render failed: {exc}")
        # A present LibreOffice that produces NO output is not a server fault —
        # it's a confined/broken install (e.g. the Ubuntu snap can't read files
        # outside $HOME and exits 0 with an empty result). The contract is
        # "never 503/500 for a preview we can't rasterize"; a hard 500 here
        # broke that. Fall through to the SAME extracted-text degrade the
        # LibreOffice-missing path uses, so the preview still returns a usable
        # response. (The apt libreoffice the coder image ships is unconfined and
        # renders normally — verified in-pod 2026-08-11.)
        if pngs:
            if total:
                return JSONResponse({
                    "total": len(pngs), "name": name, "type": "pptx",
                    "kind": "presentation", "libreoffice_available": True,
                })
            if slide < 1 or slide > len(pngs):
                raise HTTPException(
                    status_code=404,
                    detail=f"Slide {slide} out of range (1-{len(pngs)})",
                )
            return FileResponse(
                pngs[slide - 1],
                media_type="image/png",
                headers={"Cache-Control": "private, no-cache"},
            )
        # else: empty render → drop into the text-fallback path below.

    # PPTX, LibreOffice missing OR unable to render — degrade to extracted text
    # (never 503 / 500).
    if is_legacy:
        return _text_fallback(
            kind="presentation", name=name, total=1,
            content=(f"Legacy binary `{ext}` preview needs LibreOffice "
                     f"(install it for raster slide previews). The model can "
                     f"still use list_pptx_slides / read_pptx_slide_text."),
        )
    from ...engine.tools.builtin.pptx_tools import extract_pptx_slide_text
    try:
        from pptx import Presentation
        slide_count = len(Presentation(str(file_path)).slides)
    except ImportError:
        # Neither LibreOffice nor python-pptx. The web client renders a
        # formatted "install LibreOffice" card from libreoffice_available;
        # this body is the plain-text equivalent for other clients. The
        # `pip install 'ppxai[data]'` route only helps source installs — it's
        # a dead end for the frozen binary, so omit it there.
        hint = "Install LibreOffice to render this presentation."
        if not getattr(sys, "frozen", False):
            hint += " (Or `pip install 'ppxai[data]'` for text extraction.)"
        return _text_fallback(
            kind="presentation", name=name, total=1, content=hint,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Cannot open PPTX: {exc}")

    if total:
        return JSONResponse({
            "total": slide_count, "name": name, "type": "pptx",
            "kind": "presentation", "libreoffice_available": False,
        })
    text = extract_pptx_slide_text(file_path, slide)
    return _text_fallback(
        kind="presentation", name=name, total=slide_count,
        content=text, slide=slide,
    )


@router.get("/files/preview")
async def preview_file_by_path(
    path: str = Query(..., description="Working-dir-relative or absolute path"),
    slide: int = Query(1, ge=1, description="Slide number (1-based)"),
    total: bool = Query(False, description="Return only metadata (slide count, type)"),
    cwd_anchor: str | None = Query(None, description="Client cwd at click time"),
    s: Session = Depends(get_session_or_query),
):
    """Office preview — path-based variant. Delegates to the shared
    `render_office_preview` helper so this route and the file_id-based
    `/files/preview/{file_id}` (file_serve.py) return one identical contract.
    """
    logger.info(f"HTTP GET /files/preview - path: {path} slide: {slide} total: {total}")
    resolved = _resolve_safe_path(path, s.engine, cwd_anchor)
    return render_office_preview(
        resolved, resolved.name, resolved.suffix, _path_cache_dir(resolved),
        slide=slide, total=total,
    )


# ---------------------------------------------------------------------------
# Path-based file download (v1.18.7)
# ---------------------------------------------------------------------------
#
# Streams raw bytes with Content-Disposition: attachment so the browser
# fires its native download dialog. Used by the new download buttons in
# the file tree + view toolbar (BaseView).
#
# Security: same _resolve_safe_path check the other path-based endpoints
# use — working_dir tree OR home_dir tree. No special-casing.


@router.get("/files/download")
async def download_file(
    path: str = Query(..., description="Working-dir-relative or absolute path"),
    cwd_anchor: str | None = Query(None, description="Client cwd at click time"),
    s: Session = Depends(get_session_or_query),
):
    """Download a file as raw bytes with attachment Content-Disposition.

    v1.18.7. Returns the file with `Content-Disposition: attachment;
    filename="<basename>"` so browsers trigger the download dialog
    instead of attempting to render inline. Works for any file type
    accessible via _resolve_safe_path's security check.

    Path conventions match /files/read + /files/preview: relative
    paths resolve against working_dir; absolute paths must sit inside
    working_dir tree or home_dir tree.
    """
    logger.info(f"HTTP GET /files/download - path: {path}")
    resolved = _resolve_safe_path(path, s.engine, cwd_anchor)
    ext = resolved.suffix.lower()
    mime_type = MIME_TYPES.get(ext, "application/octet-stream")
    try:
        data = resolved.read_bytes()
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Cannot read file: {exc}")
    return Response(
        content=data,
        media_type=mime_type,
        headers={
            "Content-Disposition": f'attachment; filename="{resolved.name}"',
            "Cache-Control": "private, no-cache",
        },
    )


# Per-request upload size cap. Larger than the multi-modal-attach
# limits because workspace uploads can be entire datasets or project
# bundles being seeded into an empty /workspace (the coder.internal
# use case where pods start with nothing on disk). 100 MB matches
# the nginx ingress proxy-body-size on the coder ingress.
UPLOAD_MAX_BYTES = 100 * 1024 * 1024  # 100 MB


@router.post("/files/upload")
async def upload_file(
    file: UploadFile = File(..., description="The uploaded file"),
    path: str = Query(..., description="Destination DIRECTORY (working-dir-relative or absolute)"),
    overwrite: bool = Query(False, description="Overwrite existing file at the target name"),
    cwd_anchor: str | None = Query(None, description="Client cwd at click time"),
    s: Session = Depends(get_session_or_query),
):
    """Upload a file from the user's local PC into the workspace.

    v1.18.7. Complements the multi-modal attach path (which stages
    files into conversation context) — this writes the bytes to disk
    under ``<path>/<file.filename>`` so the agent can subsequently
    ``read_file``, ``edit_file``, etc. against them like any
    workspace file. Closes the gap in k8s deployments (coder.internal)
    where pods start with empty /workspace and users have no
    other way to populate it (not everyone uses git; many users are
    not software developers).

    Path conventions mirror ``/files/preview`` and ``/files/download``:

    - relative paths resolve against working_dir
    - absolute paths must sit inside working_dir tree or home_dir tree
    - ``_resolve_safe_path`` security check (same 403/404 codes)

    ``path`` is a DIRECTORY. The uploaded file lands at
    ``<path>/<file.filename>`` where ``<file.filename>`` is sanitized
    to its basename — no directory components from the upload are
    honored (so e.g. ``../../etc/passwd`` in the filename can't escape
    the destination directory).

    Status codes:
    - 200 OK with ``{"path", "name", "size", "overwrote"}`` on success
    - 400 if ``path`` is not a directory, or filename is empty / invalid
    - 403 if the destination would land outside allowed paths
    - 404 if ``path`` doesn't exist
    - 409 if destination exists and ``overwrite=false``
    - 413 if upload exceeds ``UPLOAD_MAX_BYTES`` (100 MB)
    - 500 on OSError during write
    """
    logger.info(
        f"HTTP POST /files/upload - path: {path} filename: {file.filename!r}"
    )

    if not file.filename:
        raise HTTPException(status_code=400, detail="Missing filename in upload")

    # Sanitize to basename only — drop any directory components that
    # might have been smuggled in via the filename field. Forbid the
    # special "." / ".." names so a malicious upload can't replace the
    # destination directory itself.
    safe_name = Path(file.filename).name
    if not safe_name or safe_name in (".", ".."):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid filename {file.filename!r}",
        )

    # Resolve destination dir with the same security check the rest of
    # /files/* uses. allow_directory=True opts into directory targets
    # (read/preview/download keep their file-only default).
    resolved_dir = _resolve_safe_path(path, s.engine, cwd_anchor, allow_directory=True)
    if not resolved_dir.is_dir():
        raise HTTPException(
            status_code=400,
            detail=f"Upload destination is not a directory: {path!r}",
        )

    dest = resolved_dir / safe_name
    # The parent was security-checked by _resolve_safe_path (and `.resolve()`d,
    # so it's canonical). Path.name can't contain separators or `..`, so the
    # join can't escape via the name. The one remaining escape is `dest` itself
    # being a pre-planted symlink: `open(dest, "wb")` would follow it and write
    # outside the allowed tree. Refuse to write through a symlinked destination.
    if dest.is_symlink():
        logger.warning(f"  Upload denied: destination is a symlink: {dest}")
        raise HTTPException(
            status_code=403,
            detail="Upload destination is a symlink; refusing to write through it",
        )

    existed = dest.exists()
    if existed and not overwrite:
        raise HTTPException(
            status_code=409,
            detail=(
                f"File exists: {safe_name!r}. "
                f"Re-send with overwrite=true to replace."
            ),
        )

    # Stream to disk with running size cap. Reading in 1 MB chunks
    # bounds peak memory regardless of upload size, and the early
    # abort + unlink on overflow keeps a partial file from lingering.
    total = 0
    CHUNK = 1024 * 1024
    try:
        with open(dest, "wb") as f_out:
            while True:
                chunk = await file.read(CHUNK)
                if not chunk:
                    break
                total += len(chunk)
                if total > UPLOAD_MAX_BYTES:
                    # Truncate + remove the partial file before raising.
                    f_out.close()
                    dest.unlink(missing_ok=True)
                    raise HTTPException(
                        status_code=413,
                        detail=(
                            f"Upload exceeds limit "
                            f"({UPLOAD_MAX_BYTES // (1024 * 1024)} MB). "
                            f"Sent {total} bytes."
                        ),
                    )
                f_out.write(chunk)
    except HTTPException:
        raise
    except OSError as exc:
        dest.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail=f"Cannot write file: {exc}")

    return {
        "path": str(dest),
        "name": safe_name,
        "size": total,
        "overwrote": existed,
    }
