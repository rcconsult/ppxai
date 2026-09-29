"""No hint may tell a user to install ppxai from PyPI.

ppxai is not published on PyPI, and the `ppxai` name there belongs to an
unrelated project, so `pip install ppxai` / `pip install 'ppxai[data]'`
installs someone else's code. Runtime hints go through
`ppxai.constants.install_extra_hint()`; docs use the source forms
(`uv sync --extra X`, or `pip install "ppxai[X] @ git+https://…"`).

History (CHANGELOG, docs/archive/, old release notes) is exempt: it records
what was said then.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from ppxai.constants import PPXAI_GIT_URL, install_extra_hint

REPO = Path(__file__).resolve().parents[1]
THIS = Path(__file__).resolve().relative_to(REPO).as_posix()

TEXT_SUFFIXES = {".py", ".md", ".toml", ".txt", ".js", ".ts", ".json", ".yml", ".yaml",
                 ".sh", ".ps1", ".cfg", ".ini", ".html", ".rst", ".spec"}

# pip / pip3 / pipx / uv pip / uv tool, then ppxai (optionally [extras],
# optionally quoted) NOT followed by ` @ ` (the git+ source form is fine).
BARE_INSTALL = re.compile(
    r"\b(?:pip3?|pipx|uv\s+pip|uv\s+tool)\s+install\s+(?:-\S+\s+)*"
    # The lookaheads look past an optional closing quote, so backtracking out
    # of `[extras]` or the quote cannot sneak a match in front of ` @ git+`.
    r"['\"]?ppxai(?:\[[^\]]*\])?['\"]?(?!['\"]?\s*@)(?!['\"]?[\[\w./-])")

# Lines that name the bare command in order to WARN against it.
WARNINGS = ("not on PyPI", "installs something else", "unrelated project")


def _exempt(rel: str) -> bool:
    return (rel == "CHANGELOG.md" or rel.startswith("docs/archive/")
            or re.fullmatch(r"docs/release-notes-v[\d.]+\.md", rel) is not None
            or rel == THIS)


def _tracked_text_files() -> list[str]:
    out = subprocess.run(["git", "ls-files"], cwd=REPO, capture_output=True, text=True,
                         check=True, encoding="utf-8")
    return [p for p in out.stdout.splitlines() if Path(p).suffix in TEXT_SUFFIXES]


def _offenders() -> list[str]:
    found = []
    for rel in _tracked_text_files():
        if _exempt(rel):
            continue
        try:
            text = (REPO / rel).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for n, line in enumerate(text.splitlines(), 1):
            if BARE_INSTALL.search(line) and not any(w in line for w in WARNINGS):
                found.append(f"{rel}:{n}: {line.strip()[:140]}")
    return found


def test_nothing_tells_a_user_to_install_ppxai_from_pypi():
    offenders = _offenders()
    assert offenders == [], (
        "These lines tell a user to `pip install ppxai…`, which installs an UNRELATED "
        "PyPI project. Use ppxai.constants.install_extra_hint() in code, or the "
        f'`uv sync --extra X` / `pip install "ppxai[X] @ git+{PPXAI_GIT_URL}"` forms '
        "in docs:\n  " + "\n  ".join(offenders))


def test_the_fence_catches_the_forms_it_must():
    for bad in ("pip install ppxai", "pip install 'ppxai[data]'", 'pip3 install "ppxai[tui]"',
                "uv pip install ppxai[server]", "pipx install ppxai", "pip install -U ppxai"):
        assert BARE_INSTALL.search(bad), bad
    for ok in (f'pip install "ppxai[data] @ git+{PPXAI_GIT_URL}"', "pip install ppxai-sre",
               "uv sync --extra data", "pip install mcp"):
        assert not BARE_INSTALL.search(ok), ok


def test_the_runtime_hint_is_the_source_form():
    hint = install_extra_hint("data")
    assert "uv sync --extra data" in hint
    assert f'"ppxai[data] @ git+{PPXAI_GIT_URL}"' in hint
    assert not BARE_INSTALL.search(hint)
