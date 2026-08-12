"""Cross-platform LibreOffice discovery (ppxai/common/libreoffice.py).

Regression for the macOS gap: the old `shutil.which("libreoffice")` probe
missed macOS's `soffice` inside `/Applications/LibreOffice.app`, so a plain
`brew install --cask libreoffice` left office raster preview dead. The
resolver now covers PATH (`libreoffice`/`soffice`), the macOS .app bundle,
Windows Program Files, and a `PPXAI_LIBREOFFICE` override.
"""

from __future__ import annotations

import os
import sys

import pytest

from ppxai.common import libreoffice as lo


def _make_exe(tmp_path, name="soffice"):
    p = tmp_path / name
    p.write_text("#!/bin/sh\n")
    p.chmod(0o755)
    return p


class TestFindLibreOffice:
    def test_env_override_wins(self, tmp_path, monkeypatch):
        exe = _make_exe(tmp_path, "lo-custom")
        monkeypatch.setenv("PPXAI_LIBREOFFICE", str(exe))
        # PATH would also resolve, but the override takes precedence.
        monkeypatch.setattr(lo.shutil, "which", lambda n: "/usr/bin/libreoffice")
        assert lo.find_libreoffice() == str(exe)

    def test_env_override_nonexistent_falls_through(self, tmp_path, monkeypatch):
        monkeypatch.setenv("PPXAI_LIBREOFFICE", str(tmp_path / "nope"))
        monkeypatch.setattr(
            lo.shutil, "which",
            lambda n: "/usr/bin/libreoffice" if n == "libreoffice" else None,
        )
        assert lo.find_libreoffice() == "/usr/bin/libreoffice"

    def test_path_libreoffice(self, monkeypatch):
        monkeypatch.delenv("PPXAI_LIBREOFFICE", raising=False)
        monkeypatch.setattr(
            lo.shutil, "which",
            lambda n: "/usr/bin/libreoffice" if n == "libreoffice" else None,
        )
        assert lo.find_libreoffice() == "/usr/bin/libreoffice"

    def test_path_soffice_when_no_libreoffice(self, monkeypatch):
        """macOS/user-symlink case: only `soffice` resolves."""
        monkeypatch.delenv("PPXAI_LIBREOFFICE", raising=False)
        monkeypatch.setattr(
            lo.shutil, "which",
            lambda n: "/opt/soffice" if n == "soffice" else None,
        )
        assert lo.find_libreoffice() == "/opt/soffice"

    def test_well_known_path_when_not_on_path(self, tmp_path, monkeypatch):
        """The core macOS fix: nothing on PATH, but the .app-style absolute
        path exists and is returned."""
        exe = _make_exe(tmp_path)
        monkeypatch.delenv("PPXAI_LIBREOFFICE", raising=False)
        monkeypatch.setattr(lo.shutil, "which", lambda n: None)
        monkeypatch.setattr(lo, "_well_known_paths", lambda: [tmp_path / "missing", exe])
        assert lo.find_libreoffice() == str(exe)
        assert lo.libreoffice_available() is True

    def test_none_when_absent(self, monkeypatch):
        monkeypatch.delenv("PPXAI_LIBREOFFICE", raising=False)
        monkeypatch.setattr(lo.shutil, "which", lambda n: None)
        monkeypatch.setattr(lo, "_well_known_paths", lambda: [])
        assert lo.find_libreoffice() is None
        assert lo.libreoffice_available() is False

    def test_macos_well_known_includes_app_bundle(self, monkeypatch):
        # Compare with as_posix(): `str(Path(...))` renders with the HOST
        # separator, so a hardcoded "/"-joined needle never matches when this
        # suite runs on Windows (the branch itself is platform-independent —
        # it reads sys.platform, which is patched here).
        monkeypatch.setattr(lo.sys, "platform", "darwin")
        paths = [p.as_posix() for p in lo._well_known_paths()]
        assert any("LibreOffice.app/Contents/MacOS/soffice" in p for p in paths)

    # NB: the Windows branch can't be reached by patching from a POSIX host —
    # monkeypatching os.name to "nt" globally breaks pathlib (WindowsPath
    # can't instantiate there). Unlike the darwin branch above (which reads
    # sys.platform and so is patchable anywhere), this one reads os.name. So
    # it's covered natively on Windows only; the well-known-path *mechanism*
    # is still covered everywhere by test_well_known_path_when_not_on_path.
    @pytest.mark.skipif(os.name != "nt", reason="reads os.name; only reachable natively on Windows")
    def test_windows_well_known_includes_program_files(self, monkeypatch):
        monkeypatch.setenv("PROGRAMFILES", r"C:\Program Files")
        paths = [p.as_posix() for p in lo._well_known_paths()]
        assert any(p.endswith("LibreOffice/program/soffice.exe") for p in paths)


class TestLibreOfficeCanRead:
    """Item: `libreoffice_can_read(dir)` — the capability probe distinct from
    mere presence. A snap-confined LibreOffice exists but can't read /tmp and
    exits 0 with no output; this probe does a real convert and checks output,
    so callers (test guards, and the preview route's degrade) branch on what
    LibreOffice can actually do, not just that it's installed."""

    def _fake_soffice(self, tmp_path, *, emit: bool):
        """A stand-in soffice: parses `--outdir <dir> <src>` and either writes a
        <src>.pdf into outdir (emit=True) or writes nothing (emit=False, the
        confined/broken case). Always exits 0 — like the real snap does.

        Returned as a single spawnable path because `find_libreoffice()` yields
        one token, so the probe's argv shape must be preserved. Windows has no
        shebang mechanism: an extensionless `#!/usr/bin/env python3` script is
        rejected by CreateProcess with WinError 193, which
        `libreoffice_can_read` catches as OSError → False. That made
        `test_true_when_convert_emits_output` fail and, worse, made both
        emit=False cases pass for the wrong reason. So the launcher is a `.cmd`
        shim there and a shebang script elsewhere.
        """
        body = (
            "import sys\n"
            "from pathlib import Path\n"
            f"emit = {emit!r}\n"
            "args = sys.argv[1:]\n"
            "outdir = args[args.index('--outdir')+1]\n"
            "src = Path(args[-1])\n"
            "if emit:\n"
            "    (Path(outdir)/(src.stem + '.pdf')).write_bytes(b'%PDF-1.4\\n')\n"
            "sys.exit(0)\n"
        )
        script = tmp_path / "_fake_soffice_impl.py"
        script.write_text(body, encoding="utf-8")

        if os.name == "nt":
            exe = tmp_path / "soffice.cmd"
            exe.write_text(
                f'@echo off\r\n"{sys.executable}" "{script}" %*\r\n',
                encoding="utf-8",
            )
        else:
            exe = tmp_path / "soffice"
            exe.write_text(
                f"#!{sys.executable}\n{body}", encoding="utf-8"
            )
        exe.chmod(0o755)
        return exe

    def test_false_when_no_binary(self, monkeypatch, tmp_path):
        monkeypatch.setattr(lo, "find_libreoffice", lambda: None)
        assert lo.libreoffice_can_read(tmp_path) is False

    def test_true_when_convert_emits_output(self, monkeypatch, tmp_path):
        exe = self._fake_soffice(tmp_path, emit=True)
        monkeypatch.setattr(lo, "find_libreoffice", lambda: str(exe))
        assert lo.libreoffice_can_read(tmp_path) is True

    def test_false_when_convert_emits_nothing(self, monkeypatch, tmp_path):
        # The confinement signature: exit 0, no output. Presence != capability.
        exe = self._fake_soffice(tmp_path, emit=False)
        monkeypatch.setattr(lo, "find_libreoffice", lambda: str(exe))
        assert lo.libreoffice_can_read(tmp_path) is False

    def test_false_on_spawn_failure(self, monkeypatch, tmp_path):
        # A resolved path that isn't actually runnable → False, never raises.
        monkeypatch.setattr(lo, "find_libreoffice", lambda: str(tmp_path / "nope"))
        assert lo.libreoffice_can_read(tmp_path) is False
