"""ADR 0006 Foundation — ArtifactRegistry round-trip + dispatch tests.

Pins the contract between MarshallableArtifact + ArtifactRegistry that
v2 session JSON (Step 4 pending) and v1.19.x agent-platform artifact
persistence depend on. Specifically:

- Each registered kind round-trips through to_dict / from_dict
- Registry dispatch routes by data["kind"] to the right concrete class
- Unknown kinds return None (forward-compat for newer-version artifacts)
- Re-registration semantics: same class idempotent, different class raises
- Discoverability helpers (list_registered_kinds, has_kind, class_for_kind)
- Pattern alignment with ppxai/rendering/base.py::Renderer (decorator,
  mechanical dispatch, no if/elif chains)

These tests are sentinels: a future Phase 7 cleanup that drops in-block
keys from producers + adds new kinds (sub-agents, tool artifacts) MUST
not break these contracts. Adding a new artifact kind = add a test
class here following the same shape.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar

import pytest

from ppxai.engine.artifact_registry import ArtifactRegistry
from ppxai.engine.types import (
    ArtifactRef,
    ImageAttachmentRef,
    MarshallableArtifact,
    OfficeAttachmentRef,
    PdfAttachmentRef,
    TextAttachmentRef,
)

# =============================================================================
# Registry — discoverability
# =============================================================================


class TestRegistryDiscoverability:
    """Pin the 4 v1.18.6 kinds. Bump the count when adding new kinds in
    v1.19.x (sub-agent outputs, tool artifacts, plan documents, etc.)."""

    def test_known_kinds_pinned(self):
        kinds = ArtifactRegistry.list_registered_kinds()
        assert kinds == ["image", "office", "pdf", "text"], (
            f"Foundation kinds drift detected. Expected exactly the 4 v1.18.6 "
            f"kinds; got {kinds!r}. Adding a kind in v1.19.x: bump this "
            f"assertion + add a per-kind round-trip test below."
        )

    def test_has_kind_for_each_registered(self):
        for kind in ["image", "office", "pdf", "text"]:
            assert ArtifactRegistry.has_kind(kind), f"missing kind: {kind!r}"

    def test_has_kind_false_for_unknown(self):
        assert not ArtifactRegistry.has_kind("nonexistent_kind")
        assert not ArtifactRegistry.has_kind("")

    def test_class_for_kind_lookup(self):
        assert ArtifactRegistry.class_for_kind("image") is ImageAttachmentRef
        assert ArtifactRegistry.class_for_kind("pdf") is PdfAttachmentRef
        assert ArtifactRegistry.class_for_kind("office") is OfficeAttachmentRef
        assert ArtifactRegistry.class_for_kind("text") is TextAttachmentRef
        assert ArtifactRegistry.class_for_kind("unknown") is None


# =============================================================================
# Per-kind round-trip — to_dict → deserialize → equal
# =============================================================================


class TestImageAttachmentRefRoundTrip:
    def test_full_payload_round_trip(self):
        original = ImageAttachmentRef(
            block_index=0, name="screenshot.png",
            file_id="sha256:abc123", media_type="image/png",
        )
        data = original.to_dict()
        # Pin the wire shape so consumers can rely on it.
        assert data == {
            "kind": "image",
            "_schema_version": 1,
            "block_index": 0,
            "name": "screenshot.png",
            "file_id": "sha256:abc123",
            "media_type": "image/png",
        }
        restored = ArtifactRegistry.deserialize(data)
        assert isinstance(restored, ImageAttachmentRef)
        assert restored == original

    def test_round_trip_with_empty_optional_fields(self):
        original = ImageAttachmentRef(block_index=2, name="x.png")
        restored = ArtifactRegistry.deserialize(original.to_dict())
        assert restored == original
        assert restored.file_id == ""

    def test_unsupported_schema_version_raises(self):
        with pytest.raises(ValueError, match="_schema_version=99"):
            ImageAttachmentRef.from_dict({
                "kind": "image", "_schema_version": 99,
                "block_index": 0, "name": "x.png",
            })

    def test_missing_schema_version_defaults_to_1(self):
        ref = ImageAttachmentRef.from_dict({
            "kind": "image",
            "block_index": 0,
            "name": "legacy.png",
            "file_id": "sha:legacy",
            "media_type": "image/png",
        })
        assert ref.name == "legacy.png"


class TestPdfAttachmentRefRoundTrip:
    def test_full_payload_round_trip(self):
        original = PdfAttachmentRef(
            block_index=1, name="report.pdf", file_id="sha256:def",
            media_type="application/pdf", page_count=42,
        )
        data = original.to_dict()
        assert data == {
            "kind": "pdf",
            "_schema_version": 1,
            "block_index": 1,
            "name": "report.pdf",
            "file_id": "sha256:def",
            "media_type": "application/pdf",
            "page_count": 42,
        }
        restored = ArtifactRegistry.deserialize(data)
        assert isinstance(restored, PdfAttachmentRef)
        assert restored == original

    def test_unknown_page_count_serializes_as_null(self):
        original = PdfAttachmentRef(
            block_index=0, name="r.pdf", file_id="sha:x",
        )
        assert original.page_count is None
        data = original.to_dict()
        assert data["page_count"] is None
        restored = ArtifactRegistry.deserialize(data)
        assert restored.page_count is None


class TestOfficeAttachmentRefRoundTrip:
    def test_xlsx_with_sheet_count(self):
        original = OfficeAttachmentRef(
            block_index=0, name="data.xlsx", file_id="sha:x",
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            sheet_count=4,
        )
        data = original.to_dict()
        assert data["kind"] == "office"
        assert data["sheet_count"] == 4
        assert data["slide_count"] is None
        restored = ArtifactRegistry.deserialize(data)
        assert restored == original

    def test_pptx_with_slide_count(self):
        original = OfficeAttachmentRef(
            block_index=0, name="deck.pptx", file_id="sha:y",
            media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
            slide_count=18,
        )
        data = original.to_dict()
        assert data["slide_count"] == 18
        assert data["sheet_count"] is None
        restored = ArtifactRegistry.deserialize(data)
        assert restored == original


class TestTextAttachmentRefRoundTrip:
    def test_markdown_with_char_count(self):
        original = TextAttachmentRef(
            block_index=0, name="notes.md", file_id="sha:m",
            media_type="text/markdown", char_count=2048,
        )
        data = original.to_dict()
        assert data["kind"] == "text"
        assert data["char_count"] == 2048
        restored = ArtifactRegistry.deserialize(data)
        assert restored == original

    def test_inline_only_with_empty_file_id(self):
        original = TextAttachmentRef(
            block_index=1, name="config.yaml",
            media_type="text/yaml", char_count=128,
        )
        assert original.file_id == ""
        restored = ArtifactRegistry.deserialize(original.to_dict())
        assert restored == original


# =============================================================================
# Registry dispatch — unknown / malformed / forward-compat
# =============================================================================


class TestRegistryDispatchSafety:
    """Forward-compat property required by ADR 0003 — agent runs may
    contain newer-version artifact kinds an older ppxai doesn't
    recognize. `deserialize` returns None gracefully so loaders skip
    unknown kinds rather than crashing the whole load."""

    def test_unknown_kind_returns_none(self):
        result = ArtifactRegistry.deserialize({
            "kind": "future_subagent_artifact",
            "_schema_version": 1,
            "block_index": 0,
        })
        assert result is None

    def test_missing_kind_returns_none(self):
        result = ArtifactRegistry.deserialize({
            "block_index": 0, "name": "x.png",
        })
        assert result is None

    def test_non_dict_returns_none(self):
        for bad_input in [None, "image", 42, [], ()]:
            assert ArtifactRegistry.deserialize(bad_input) is None  # type: ignore[arg-type]

    def test_empty_kind_returns_none(self):
        result = ArtifactRegistry.deserialize({"kind": "", "block_index": 0})
        assert result is None

    def test_known_kind_with_bad_payload_propagates_error(self):
        """When kind IS registered but payload is broken, the error
        propagates — that's a real data corruption signal, not a
        forward-compat case."""
        with pytest.raises((KeyError, ValueError, TypeError)):
            ArtifactRegistry.deserialize({
                "kind": "image",
                "_schema_version": 1,
                # missing required block_index
                "name": "x.png",
            })


# =============================================================================
# Registration semantics — idempotent + collision-safe
# =============================================================================


class TestRegistrationSemantics:
    def test_re_register_same_class_is_noop(self):
        ArtifactRegistry.register("image")(ImageAttachmentRef)
        assert ArtifactRegistry.class_for_kind("image") is ImageAttachmentRef

    def test_re_register_different_class_raises(self):
        @dataclass
        class FakeImage:
            SCHEMA_VERSION: ClassVar[int] = 1
            block_index: int = 0
            kind: str = "image"
            def to_dict(self) -> dict[str, Any]:
                return {}
            @classmethod
            def from_dict(cls, data: dict[str, Any]) -> "FakeImage":
                return cls()

        with pytest.raises(ValueError, match="kind='image' already registered"):
            ArtifactRegistry.register("image")(FakeImage)

    def test_register_empty_kind_raises(self):
        @dataclass
        class Whatever:
            SCHEMA_VERSION: ClassVar[int] = 1
            block_index: int = 0
            kind: str = ""
            def to_dict(self) -> dict[str, Any]: return {}
            @classmethod
            def from_dict(cls, data): return cls()

        with pytest.raises(ValueError, match="non-empty"):
            ArtifactRegistry.register("")(Whatever)

    def test_decorator_returns_class_unchanged(self):
        @dataclass
        class DummyKind:
            SCHEMA_VERSION: ClassVar[int] = 1
            block_index: int = 0
            kind: str = "test_dummy_unique_kind_for_decorator_check"
            def to_dict(self) -> dict[str, Any]:
                return {"kind": self.kind, "_schema_version": 1, "block_index": 0}
            @classmethod
            def from_dict(cls, data): return cls()

        decorated = ArtifactRegistry.register(
            "test_dummy_unique_kind_for_decorator_check"
        )(DummyKind)
        assert decorated is DummyKind  # Identity on the class object


# =============================================================================
# Protocol satisfaction — structural typing
# =============================================================================


class TestProtocolSatisfaction:
    """The 4 concrete kinds satisfy both ArtifactRef (identity) and
    MarshallableArtifact (persistence) Protocols structurally."""

    @pytest.mark.parametrize("cls,sample_args", [
        (ImageAttachmentRef, {"block_index": 0, "name": "x.png"}),
        (PdfAttachmentRef, {"block_index": 0, "name": "r.pdf"}),
        (OfficeAttachmentRef, {"block_index": 0, "name": "d.xlsx"}),
        (TextAttachmentRef, {"block_index": 0, "name": "n.md"}),
    ])
    def test_satisfies_artifact_ref_protocol(self, cls, sample_args):
        instance = cls(**sample_args)
        assert isinstance(instance, ArtifactRef)

    @pytest.mark.parametrize("cls,sample_args", [
        (ImageAttachmentRef, {"block_index": 0, "name": "x.png"}),
        (PdfAttachmentRef, {"block_index": 0, "name": "r.pdf"}),
        (OfficeAttachmentRef, {"block_index": 0, "name": "d.xlsx"}),
        (TextAttachmentRef, {"block_index": 0, "name": "n.md"}),
    ])
    def test_satisfies_marshallable_artifact_protocol(self, cls, sample_args):
        instance = cls(**sample_args)
        assert isinstance(instance, MarshallableArtifact)

    @pytest.mark.parametrize("cls", [
        ImageAttachmentRef, PdfAttachmentRef, OfficeAttachmentRef, TextAttachmentRef,
    ])
    def test_has_required_class_var(self, cls):
        assert hasattr(cls, "SCHEMA_VERSION")
        assert isinstance(cls.SCHEMA_VERSION, int)
        assert cls.SCHEMA_VERSION >= 1

    @pytest.mark.parametrize("cls,sample_args", [
        (ImageAttachmentRef, {"block_index": 0, "name": "x.png"}),
        (PdfAttachmentRef, {"block_index": 0, "name": "r.pdf"}),
        (OfficeAttachmentRef, {"block_index": 0, "name": "d.xlsx"}),
        (TextAttachmentRef, {"block_index": 0, "name": "n.md"}),
    ])
    def test_to_dict_includes_required_universal_fields(self, cls, sample_args):
        """Every artifact's to_dict must include kind, _schema_version,
        block_index — the universal triplet the registry relies on."""
        instance = cls(**sample_args)
        data = instance.to_dict()
        assert "kind" in data
        assert "_schema_version" in data
        assert "block_index" in data
        assert data["kind"] == instance.kind
