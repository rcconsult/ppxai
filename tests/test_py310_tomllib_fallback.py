"""ppxai supports Python 3.10 (`requires-python >=3.10`), but `tomllib`
arrived in 3.11. Every module that imports it must fall back to the
`tomli` backport, which pyproject declares for `python_version < '3.11'`.

Three sites once imported it bare; on 3.10 each failed quietly (two behind
`except Exception`), found only by the Linux test run.
"""

from __future__ import annotations

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
PKG = ROOT / "ppxai"


def _sites() -> list[pathlib.Path]:
    return sorted(p for p in PKG.rglob("*.py") if re.search(r"^\s*import tomllib\b", p.read_text(encoding="utf-8"), re.M))


def test_there_are_sites_to_check():
    assert len(_sites()) >= 3, "the scan found no tomllib imports; the scan itself is broken"


def test_every_tomllib_import_falls_back_to_tomli():
    missing = [
        str(p.relative_to(ROOT)) for p in _sites()
        if "import tomli as tomllib" not in p.read_text(encoding="utf-8")
    ]
    assert not missing, (
        f"{missing} import tomllib without a `tomli` fallback, which breaks on "
        "Python 3.10: wrap it in try/except ModuleNotFoundError: import tomli as tomllib"
    )


def test_tomli_is_declared_for_python_310():
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert re.search(r'"tomli[^"]*;\s*python_version\s*<\s*\'3\.11\'"', pyproject)
