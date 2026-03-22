"""
File operations endpoints (search, list, tree, read, write, image).
"""

import base64
import os
import time
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from typing import Optional

from ...common.logger import get_logger
from ..models import FileReadRequest, FileSearchRequest, FileWriteRequest
from ..state import Session, get_session, is_path_allowed, MIME_TYPES

logger = get_logger("server")

# Directories to ignore when searching for files (same as TUI completer)
IGNORE_DIRS = {'.git', 'node_modules', '__pycache__', '.venv', 'venv', '.tox', 'dist', 'build', '.eggs', '.mypy_cache'}

router = APIRouter()


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

    try:
        for path in working_dir.rglob('*'):
            if len(results) >= request.max_results:
                break
            try:
                # Check if file - can fail on network paths (WinError 4350)
                if path.is_file():
                    # Skip files in ignored directories
                    if any(ignored in path.parts for ignored in IGNORE_DIRS):
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
    path: Optional[str] = None,
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

    filtered = []
    for entry in entries:
        name = entry.name
        if not a and name.startswith('.'):
            continue
        if entry.is_dir() and name in IGNORE_DIRS:
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
    return {"files": files, "path": str(target), "at_fs_root": at_fs_root}


@router.get("/files/tree")
async def get_file_tree(
    path: Optional[str] = None,
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
                if name in IGNORE_DIRS:
                    continue
                dir_count += 1
                children.append(build_tree(entry, current_depth + 1))
            else:
                file_count += 1
                children.append({"label": name, "children": []})

        return {"label": directory.name + "/", "children": children}

    tree = build_tree(target, 0)
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

    # Allow files in working directory tree or home directory tree
    if not (is_path_allowed(path, working_dir) or str(path).startswith(str(home_dir))):
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
    s: Session = Depends(get_session)
):
    """Serve raw image file for inline display in chat bubbles (v1.16.2).

    Returns the image binary with correct Content-Type header.
    Used by marked.js ![alt](/files/image/path) in chat messages.
    """

    path = Path(filepath)
    if not path.is_absolute():
        working_dir = Path(s.engine.get_working_dir() or os.getcwd())
        path = working_dir / filepath
    path = path.resolve()

    # Security: same checks as /files/read
    working_dir = Path(s.engine.get_working_dir() or os.getcwd()).resolve()
    home_dir = Path.home().resolve()
    if not (is_path_allowed(path, working_dir) or str(path).startswith(str(home_dir))):
        raise HTTPException(status_code=403, detail="Access denied")

    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail=f"Not found: {filepath}")

    ext = path.suffix.lower()
    mime_type = MIME_TYPES.get(ext)
    if not mime_type or not mime_type.startswith('image/'):
        raise HTTPException(status_code=400, detail=f"Not an image: {filepath}")

    return FileResponse(path, media_type=mime_type)


@router.post("/files/read")
async def read_file(
    request: FileReadRequest,
    s: Session = Depends(get_session)
):
    """Read file contents (v1.13.1 - for /show command).

    Reads a file from the working directory or absolute path.
    Supports @search-query format for fuzzy file matching.

    Args:
        request: FileReadRequest with path

    Returns:
        JSON: {"filename", "content", "size", "lines"}

    v1.13.10: Supports X-Session-Id header for session isolation.
    """

    logger.info(f"HTTP POST /files/read - path: {request.path}")
    logger.debug(f"  Working directory: {s.engine.get_working_dir()}")

    filepath = request.path.strip()

    # Handle @search-query by searching for files
    if filepath.startswith('@'):
        query = filepath[1:]  # Remove @
        # Simple file search in working directory
        working_dir = Path(s.engine.get_working_dir() or os.getcwd())
        matches = []

        try:
            for path in working_dir.rglob('*'):
                try:
                    # Check if file - can fail on network paths (WinError 4350)
                    if path.is_file():
                        if query.lower() in path.name.lower():
                            matches.append(path)
                            if len(matches) >= 1:  # Just get first match
                                break
                except OSError:
                    # Network file unavailable, skip it
                    pass
        except (PermissionError, OSError):
            pass

        if not matches:
            raise HTTPException(status_code=404, detail=f"No files found matching: {query}")

        filepath = str(matches[0])

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

    # Allow files in working directory tree (parent or child) or home directory tree
    if not (is_path_allowed(path, working_dir) or str(path).startswith(str(home_dir))):
        logger.warning(f"  Access denied: {path} not in {working_dir} tree or {home_dir}")
        raise HTTPException(
            status_code=403, detail="Access denied: path outside allowed directories"
        )

    if not path.exists():
        logger.warning(f"  File not found: {path}")
        raise HTTPException(
            status_code=404,
            detail=f"File not found: {filepath} (resolved: {path})"
        )

    if not path.is_file():
        raise HTTPException(status_code=400, detail=f"Not a file: {filepath}")

    # Image and PDF preview support
    image_extensions = {'.png', '.jpg', '.jpeg', '.gif', '.webp', '.svg', '.bmp', '.ico'}
    ext = path.suffix.lower()
    size = path.stat().st_size

    if ext in image_extensions or ext == '.pdf':
        # Return base64-encoded binary for preview
        try:
            content_bytes = path.read_bytes()
            content_b64 = base64.b64encode(content_bytes).decode('ascii')

            # Determine MIME type and file type
            mime_type = MIME_TYPES.get(ext, 'application/octet-stream')
            file_type = 'pdf' if ext == '.pdf' else 'image'

            # Return relative path from working_dir so the web editor saves to the
            # correct location (not just the basename in the working directory root).
            try:
                rel_name = path.relative_to(working_dir).as_posix()
            except ValueError:
                rel_name = path.name

            return {
                "filename": rel_name,
                "path": str(path),
                "type": file_type,
                "mime_type": mime_type,
                "content": content_b64,
                "size": size
            }
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Error reading {file_type}: {str(e)}")

    try:
        content = path.read_text(encoding='utf-8')
        lines = content.count('\n') + 1

        # Return relative path from working_dir so the web editor saves to the
        # correct location (not just the basename in the working directory root).
        try:
            rel_name = path.relative_to(working_dir).as_posix()
        except ValueError:
            rel_name = path.name

        return {
            "filename": rel_name,
            "path": str(path),
            "type": "text",
            "content": content,
            "size": size,
            "lines": lines
        }
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="Cannot read binary file")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error reading file: {str(e)}")
