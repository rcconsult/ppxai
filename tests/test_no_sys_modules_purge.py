"""No test purges `sys.modules` by computed name in the pytest process (debt Item 81).

A fixture in `test_custom_endpoint_integration.py` once deleted every
`ppxai.engine.providers*` module and never restored them. Every module
imported afterwards got a second copy of each provider class, so
`provider_class_for("myrouter") is OpenAICompatibleProvider` failed in
`test_oneshot_grounding.py` with both sides printing the same class
path, and only when the two files ran in that order.

The fence is structural: a `del sys.modules[<expr>]` or
`sys.modules.pop(<expr>)` whose key is not a string literal is a purge
driven by a loop or prefix match, and in-process that leaks into every
later test module. Deleting a single named leaf (a string literal) is
allowed. Code inside a string that runs in a subprocess is not parsed
here, so a child interpreter may purge freely.
"""

from __future__ import annotations

import ast
from pathlib import Path

TESTS_DIR = Path(__file__).parent


def _is_sys_modules(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Attribute)
        and node.attr == "modules"
        and isinstance(node.value, ast.Name)
        and node.value.id == "sys"
    )


def _computed_purges(source: str) -> list[int]:
    lines = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Delete):
            for target in node.targets:
                if (
                    isinstance(target, ast.Subscript)
                    and _is_sys_modules(target.value)
                    and not isinstance(target.slice, ast.Constant)
                ):
                    lines.append(node.lineno)
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "pop"
            and _is_sys_modules(node.func.value)
            and node.args
            and not isinstance(node.args[0], ast.Constant)
        ):
            lines.append(node.lineno)
    return sorted(lines)


def test_no_test_module_purges_sys_modules_by_computed_name():
    offenders = {}
    for path in sorted(TESTS_DIR.rglob("*.py")):
        hits = _computed_purges(path.read_text(encoding="utf-8"))
        if hits:
            offenders[str(path.relative_to(TESTS_DIR))] = hits
    assert not offenders, (
        "A test deletes sys.modules entries by computed name in the pytest "
        f"process: {offenders}. Later test modules then import second copies "
        "of those modules, and class-identity checks (`is`) fail depending on "
        "test order (debt Item 81). Use monkeypatch.delitem(sys.modules, name) "
        "so teardown restores the originals, or run the purge in a subprocess."
    )


def test_the_detector_catches_the_item_81_shape():
    planted = (
        "import sys\n"
        "for mod_name in list(sys.modules.keys()):\n"
        "    if 'ppxai.engine.providers' in mod_name:\n"
        "        del sys.modules[mod_name]\n"
        "sys.modules.pop(mod_name, None)\n"
    )
    assert _computed_purges(planted) == [4, 5]


def test_the_detector_allows_a_named_leaf():
    allowed = (
        "import sys\n"
        "del sys.modules['ppxai._build_info']\n"
        "sys.modules.pop('main', None)\n"
    )
    assert _computed_purges(allowed) == []
