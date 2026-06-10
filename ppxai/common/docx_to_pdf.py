"""Word document → PDF conversion via LibreOffice headless.

Extracted from `ppxai.server.routes.file_serve` during the v1.18.0
stabilization pass (Phase 5g). The previous location was a private
helper (`_convert_docx_to_pdf`) that tests had to import directly,
violating the "go via interfaces to ensure object contracts" rule.

Kept as a tight single-function module with an explicit contract:
given a `.docx` / `.doc` source and a cache directory, produce a
cached `preview.pdf` inside that cache dir and return its path. No
return-via-stdout, no caller-side cleanup, no streaming — a simple
"call me, I'll give you a path to a PDF" API.

Callers must ensure LibreOffice is installed (check with
`ppxai.engine.tools.builtin.pptx_tools._libreoffice_available` —
future cleanup may consolidate that probe here). If it's not,
`convert_docx_to_pdf` raises the underlying `FileNotFoundError` /
`subprocess.CalledProcessError` — it doesn't paper over the
missing dependency with a silent fallback.

PPTX rendering lives in a separate module (`pptx_tools.py`) because
it involves per-slide PNG generation with its own cache shape. If a
future pass consolidates LibreOffice logic, both modules should
move to a shared `ppxai/common/libreoffice.py`.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path


# LibreOffice headless cold-start is slow (~2-5s) and a large document
# can take longer than the default 30s; 120s is the empirical ceiling
# for the largest documents seen in practice. Callers that need a
# different bound should open a parameter, not rewrite this.
_CONVERSION_TIMEOUT_SECONDS = 120


def convert_docx_to_pdf(source_path: Path, cache_dir: Path) -> Path:
    """Convert a Word document to PDF via LibreOffice headless.

    The result is cached as ``cache_dir / preview.pdf`` — re-invoking
    with the same cache_dir is an O(1) cache hit. Callers control
    cache lifetime by deciding where to point `cache_dir` (typically
    the file_store entry's own directory).

    Args:
        source_path: `.docx` or `.doc` file on disk. Must be a real
                     filesystem path, not an archive-relative one.
        cache_dir: Directory where the cached PDF lives. Created if
                   missing. Other files in the directory are left
                   alone; this function only manages `preview.pdf`.

    Returns:
        Absolute path to the cached PDF.

    Raises:
        FileNotFoundError: LibreOffice binary not found on PATH.
        subprocess.TimeoutExpired: Conversion exceeded the 120s budget
                                   (document probably broken / embedded
                                   content that LibreOffice can't
                                   resolve offline).
        RuntimeError: LibreOffice succeeded but produced no PDF
                      output (rare — usually a cache-dir permission
                      problem).
    """
    cache_dir = Path(cache_dir)
    cached_pdf = cache_dir / "preview.pdf"
    if cached_pdf.exists():
        # v1.18.7: validate that the cached PDF is at least as new as
        # the source — otherwise the file-tree preview keeps showing
        # the pre-edit version after the user / model rewrites the
        # .docx.
        try:
            source_mtime = source_path.stat().st_mtime
        except OSError:
            # Source missing or unreadable. Keep the cache rather than
            # serve nothing.
            return cached_pdf
        try:
            cache_mtime = cached_pdf.stat().st_mtime
        except OSError:
            cache_mtime = 0.0
        if cache_mtime >= source_mtime:
            return cached_pdf
        try:
            cached_pdf.unlink()
        except OSError:
            pass

    cache_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmpdir:
        subprocess.run(
            [
                "libreoffice", "--headless", "--norestore",
                "--convert-to", "pdf",
                "--outdir", tmpdir,
                str(source_path),
            ],
            capture_output=True,
            timeout=_CONVERSION_TIMEOUT_SECONDS,
        )
        pdf_candidates = list(Path(tmpdir).glob("*.pdf"))
        if not pdf_candidates:
            raise RuntimeError("LibreOffice produced no PDF output")
        shutil.copy2(pdf_candidates[0], cached_pdf)

    return cached_pdf
