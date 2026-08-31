"""Sentinel: every CommandResult subclass must round-trip its dataclass
fields through `to_dict()`.

Why this exists: pre-v1.18.4, ten CommandResult subclasses were
missing `to_dict()` overrides and silently dropped their custom
fields on the wire. Web/VSCode renderers received only
`type/status/message/metadata` and rendered `result.message` as the
sole user-visible output. Two known instances were already fixed
before this sentinel landed:

- v1.18.3 commit 848b4d99 — `CompositeResult.to_dict()` missing →
  `results: List[CommandResult]` dropped.
- v1.18.4 commit 462e6739 — `TreeResult.to_dict()` missing →
  `root: Dict` dropped.

The audit on 2026-05-04 surfaced ten more in the same shape. Rather
than hand-write per-class regression tests, this sentinel walks the
full class hierarchy and pins the contract: any new dataclass field
on any CommandResult subclass MUST appear in the to_dict() output.

A new subclass that adds a field but forgets the override → CI failure
on the contributing PR. That's the right gate.
"""

from __future__ import annotations

import dataclasses
import importlib

import pytest

from ppxai.commands.results import (
    CommandResult,
    ResultStatus,
)

# Fields inherited from CommandResult that are deliberately NOT in
# to_dict() — they're either internal (side_effects is promoted to the
# envelope by the route layer) or already handled by the base override.
_BASE_FIELDS = {"status", "message", "metadata", "side_effects"}


def _all_command_result_subclasses() -> list[type]:
    """Discover every class that subclasses CommandResult.

    Imports the results module to ensure all classes are registered,
    then walks `CommandResult.__subclasses__()` recursively.
    """
    importlib.import_module("ppxai.commands.results")

    seen: set[type] = set()
    stack: list[type] = list(CommandResult.__subclasses__())
    while stack:
        cls = stack.pop()
        if cls in seen:
            continue
        seen.add(cls)
        stack.extend(cls.__subclasses__())
    return sorted(seen, key=lambda c: c.__name__)


def _instantiate_with_defaults(cls: type) -> CommandResult:
    """Construct an instance using each field's default / default_factory.

    CommandResult requires `status` and `message` (no defaults). Every
    other field has a default. Pass status=SUCCESS, message="probe",
    let dataclass init fill the rest.
    """
    return cls(status=ResultStatus.SUCCESS, message="probe")


def _new_field_names(cls: type) -> set[str]:
    """Field names introduced by `cls` that aren't in the base.

    A subclass may add no new fields (e.g. DirectoryListingResult
    extends TableResult without changes). In that case the parent's
    `to_dict()` already covers everything.
    """
    fields = {f.name for f in dataclasses.fields(cls)}
    return fields - _BASE_FIELDS


# ---------------------------------------------------------------------------
# Class discovery sanity — guards against a refactor that breaks the
# subclass walker (e.g. moving classes to a different module).
# ---------------------------------------------------------------------------


class TestSubclassDiscovery:
    def test_finds_known_subclasses(self):
        names = {c.__name__ for c in _all_command_result_subclasses()}
        for expected in (
            "NotificationResult",
            "ErrorResult",
            "ConfirmationResult",
            "AIResponseResult",
            "TableResult",
            "TreeResult",
            "DirectoryListingResult",
            "DirectoryTreeResult",
            "ListResult",
            "KeyValueResult",
            "FileViewResult",
            "MarkdownResult",
            "ImageResult",
            "PreviewResult",
            "ProgressResult",
            "DiffResult",
            "ConsentResult",
            "PromptResult",
            "CompositeResult",
            "ToolExecutionResult",
            "TextResult",
        ):
            assert expected in names, (
                f"Subclass discovery missed {expected}. Did you move "
                f"the class out of ppxai.commands.results?"
            )


# ---------------------------------------------------------------------------
# THE sentinel: every subclass round-trips its fields through to_dict.
# ---------------------------------------------------------------------------


def _all_concrete_subclasses() -> list[type]:
    """All discoverable CommandResult subclasses (the base is abstract)."""
    return _all_command_result_subclasses()


@pytest.mark.parametrize(
    "cls",
    _all_concrete_subclasses(),
    ids=lambda c: c.__name__,
)
def test_to_dict_includes_every_dataclass_field(cls: type):
    """Every dataclass field on a CommandResult subclass must appear
    in the dict produced by `to_dict()`.

    Failure here means: somewhere downstream (HTTP envelope → web /
    VSCode renderer) the field is silently dropped, and the user sees
    `result.message` as the only payload. Add a `to_dict()` override
    that calls `super().to_dict()` and then sets the new field(s).
    """
    instance = _instantiate_with_defaults(cls)
    serialized = instance.to_dict()

    expected_fields = _new_field_names(cls)

    missing = expected_fields - set(serialized.keys())
    assert not missing, (
        f"{cls.__name__}.to_dict() drops fields: {sorted(missing)}.\n"
        f"Add an override:\n"
        f"    def to_dict(self) -> dict:\n"
        f"        d = super().to_dict()\n"
        f"        " + "\n        ".join(
            f'd["{f}"] = self.{f}' for f in sorted(missing)
        ) + "\n"
        "        return d"
    )


# ---------------------------------------------------------------------------
# Cross-client renderer presence — every CommandResult type the server
# can emit must have an explicit handler in BOTH web and VSCode
# renderers (or be in the documented opt-out set whose payload is
# rendered by a side-effect kind, not the result body).
# ---------------------------------------------------------------------------


# Types whose chat rendering is intentionally minimal because a
# side-effect kind drives the actual UI. The web/VSCode renderers may
# show only `result.message` for these — that's by design, not a bug.
_SIDE_EFFECT_DRIVEN = frozenset({
    "FileViewResult",       # rides open_viewer / open_editor
    "ImageResult",          # rides show_image
    "PreviewResult",        # rides open_html_preview
})


def _read_repo_file(rel: str) -> str:
    from pathlib import Path
    return (
        Path(__file__).resolve().parent.parent / rel
    ).read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "cls",
    _all_concrete_subclasses(),
    ids=lambda c: c.__name__,
)
def test_web_renderer_has_handler(cls: type):
    """Web's `ResultRenderer._handlers` must contain an entry for
    every CommandResult type the server can emit. Without one, the
    type falls through to the unknown-type fallback that shows only
    `result.message` — silently dropping any payload fields."""
    name = cls.__name__
    src = _read_repo_file("ppxai/web/shared/result-renderer.js")
    # method-shorthand: `Foo(result) {` inside the _handlers literal
    pattern = name + r"\s*\(result\)\s*\{"
    import re as _re
    assert _re.search(pattern, src), (
        f"web ResultRenderer._handlers missing handler for {name}. "
        f"Either add a handler or — if the chat rendering is driven "
        f"by a side-effect — add {name!r} to _SIDE_EFFECT_DRIVEN in "
        f"this test."
    )


@pytest.mark.parametrize(
    "cls",
    _all_concrete_subclasses(),
    ids=lambda c: c.__name__,
)
def test_vscode_renderer_has_case(cls: type):
    """VSCode's switch in commandRenderer.ts must contain a case for
    every CommandResult type."""
    name = cls.__name__
    src = _read_repo_file("vscode-extension/src/commandRenderer.ts")
    assert f"case '{name}'" in src, (
        f"VSCode CommandRenderer switch missing case for {name}. "
        f"Either add a case branch or — if the chat rendering is "
        f"driven by a side-effect — add {name!r} to "
        f"_SIDE_EFFECT_DRIVEN in this test."
    )


@pytest.mark.parametrize(
    "cls",
    _all_concrete_subclasses(),
    ids=lambda c: c.__name__,
)
def test_to_dict_is_json_serializable(cls: type):
    """Every CommandResult subclass's `to_dict()` output must be
    `json.dumps`-able — it's the HTTP envelope body (`POST /command/{name}`).
    A non-JSON value (raw dataclass, bytes, engine object) would 500 the
    route. Guards the whole class, not just the /load case that prompted it
    (debt item 32)."""
    import json
    instance = _instantiate_with_defaults(cls)
    json.dumps(instance.to_dict())


@pytest.mark.parametrize(
    "cls",
    _all_concrete_subclasses(),
    ids=lambda c: c.__name__,
)
def test_to_dict_emits_subclass_type_name(cls: type):
    """The wire `type` field must be the concrete subclass name —
    that's the dispatch key used by web/VSCode renderers. If a
    refactor changes `to_dict()` to emit the parent's name (e.g.
    `"TableResult"` for a `DirectoryListingResult`), the renderer
    would dispatch wrongly."""
    instance = _instantiate_with_defaults(cls)
    serialized = instance.to_dict()
    assert serialized.get("type") == cls.__name__, (
        f"{cls.__name__}.to_dict() emits type={serialized.get('type')!r}, "
        f"expected {cls.__name__!r}. Renderer dispatch will misroute."
    )


# ---------------------------------------------------------------------------
# Nested-result containers — `CompositeResult.results` and
# `ToolExecutionResult.artifacts` carry CommandResult instances. Their
# to_dict() must serialize each child via the child's own to_dict() so
# nested types (TableResult, ImageResult, ...) survive the wire.
# ---------------------------------------------------------------------------


class TestNestedSerialization:
    def test_composite_result_serializes_children(self):
        from ppxai.commands.results import (
            CompositeResult,
            NotificationResult,
            TableResult,
        )
        composite = CompositeResult(
            status=ResultStatus.SUCCESS,
            message="probe",
            results=[
                NotificationResult(status=ResultStatus.INFO, message="hi"),
                TableResult(
                    status=ResultStatus.SUCCESS,
                    message="t",
                    columns=["A"],
                    rows=[["x"]],
                ),
            ],
        )
        d = composite.to_dict()
        assert "results" in d
        assert len(d["results"]) == 2
        # Children carry their own type names, not the parent's.
        assert d["results"][0]["type"] == "NotificationResult"
        assert d["results"][1]["type"] == "TableResult"
        # Children's own fields survive — TableResult rows are present.
        assert d["results"][1]["rows"] == [["x"]]

    def test_tool_execution_result_serializes_artifacts(self):
        from ppxai.commands.results import (
            ImageResult,
            TableResult,
            ToolExecutionResult,
        )
        tool_result = ToolExecutionResult(
            status=ResultStatus.SUCCESS,
            message="probe",
            tool_name="python",
            duration=1.5,
            stdout="output",
            artifacts=[
                ImageResult(
                    status=ResultStatus.SUCCESS,
                    message="chart.png",
                    filepath="/tmp/c.png",
                ),
                TableResult(
                    status=ResultStatus.SUCCESS,
                    message="stats",
                    columns=["k"],
                    rows=[["v"]],
                ),
            ],
        )
        d = tool_result.to_dict()
        assert "artifacts" in d
        assert len(d["artifacts"]) == 2
        assert d["artifacts"][0]["type"] == "ImageResult"
        assert d["artifacts"][0]["filepath"] == "/tmp/c.png"
        assert d["artifacts"][1]["type"] == "TableResult"
        assert d["artifacts"][1]["rows"] == [["v"]]
