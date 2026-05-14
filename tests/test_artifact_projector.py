"""ADR 0006 Step 7a (v1.18.6) — ArtifactProjector framework tests.

Pins the per-consumer plug-n-play projection registries:

1. **Per-subclass `_registry`** — `ContextAttachmentProjector`,
   `TextMarkerProjector`, `MessageBoxProjector` each have their own
   registry; subclasses don't share state with each other or the base.

2. **Mechanical kind dispatch** — `Projector.project(ref)` looks up
   by `ref.kind`, calls the registered handler. No if/elif anywhere.

3. **All 4 v1.18.6 kinds wired** — image, pdf, office, text registered
   with all 3 projectors at engine-import time (sentinel — would catch
   a forgotten registration on a future kind addition).

4. **Strict by default** — unknown kind in `project()` raises KeyError.
   Forward-compat variant `project_optional()` returns None.

5. **Registration semantics** — empty kind, base-class registration,
   collision all raise loudly; idempotent same-handler re-decoration
   is a no-op.

6. **Pattern parity with `rendering/base.py::Renderer`** — same
   `cls.__dict__['_registry']` per-subclass model.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, ClassVar, Dict

import pytest

# Importing engine fires artifact_projections.py via __init__.py side effect.
import ppxai.engine  # noqa: F401
from ppxai.engine.artifact_projector import (
    ArtifactProjector,
    ContextAttachmentProjector,
    MessageBoxProjector,
    TextMarkerProjector,
)
from ppxai.engine.types import (
    ImageAttachmentRef,
    OfficeAttachmentRef,
    PdfAttachmentRef,
    TextAttachmentRef,
)


# =============================================================================
# 1. Per-subclass registry isolation
# =============================================================================


class TestPerSubclassRegistry:
    """Each ArtifactProjector subclass owns its own _registry. Subclasses
    don't share registry state with each other or with the base class.
    Mirrors the Renderer per-subclass model from rendering/base.py."""

    def test_each_projector_has_distinct_registry(self):
        """ContextAttachmentProjector + TextMarkerProjector + MessageBoxProjector
        each maintain a separate _registry dict. Registering on one
        doesn't leak into another."""
        ctx = ContextAttachmentProjector.__dict__.get("_registry", {})
        txt = TextMarkerProjector.__dict__.get("_registry", {})
        box = MessageBoxProjector.__dict__.get("_registry", {})
        # Different dict identities — not the same object
        assert ctx is not txt
        assert txt is not box
        assert ctx is not box

    def test_base_class_registry_stays_empty(self):
        """The bare ArtifactProjector base class never accumulates
        registrations — only its subclasses do."""
        # Base class either has no own _registry or it's empty
        base_registry = ArtifactProjector.__dict__.get("_registry", {})
        assert base_registry == {}

    def test_register_on_base_class_raises(self):
        """Decorating directly on ArtifactProjector is a coding error
        (caller forgot to subclass) — fail loudly."""
        with pytest.raises(TypeError, match="Cannot register on ArtifactProjector"):

            @ArtifactProjector.register("foo")
            def _h(ref):
                return None


# =============================================================================
# 2. Mechanical dispatch
# =============================================================================


class TestMechanicalDispatch:
    """project(ref) looks up by ref.kind, calls the handler. No
    if/elif on artifact type. Handlers receive the artifact ref and
    return whatever the projector contracts."""

    def test_image_dispatches_through_context_projector(self):
        ref = ImageAttachmentRef(
            block_index=0, name="x.png", file_id="id1",
            media_type="image/png",
        )
        dto = ContextAttachmentProjector.project(ref)
        assert dto["name"] == "x.png"
        assert dto["kind"] == "image"
        assert dto["media_type"] == "image/png"
        assert dto["file_id"] == "id1"

    def test_pdf_dispatches_through_text_marker_projector(self):
        ref = PdfAttachmentRef(
            block_index=1, name="doc.pdf", file_id="pdfid",
            media_type="application/pdf", page_count=42,
        )
        marker = TextMarkerProjector.project(ref)
        assert marker == "[Attached PDF: doc.pdf (42 pages)]"

    def test_office_dispatches_through_message_box_projector(self):
        ref = OfficeAttachmentRef(
            block_index=2, name="sheet.xlsx", file_id="xlid",
            media_type="application/vnd.ms-excel", sheet_count=3,
        )
        label = MessageBoxProjector.project(ref)
        assert "sheet.xlsx" in label

    def test_text_dispatches_through_all_three_projectors(self):
        """Same artifact instance works through every projector — the
        three projector subclasses are independent dispatch surfaces."""
        ref = TextAttachmentRef(
            block_index=3, name="notes.md", file_id="mdid",
            media_type="text/markdown", char_count=500,
        )
        ctx = ContextAttachmentProjector.project(ref)
        marker = TextMarkerProjector.project(ref)
        label = MessageBoxProjector.project(ref)
        assert ctx["name"] == "notes.md"
        assert "notes.md" in marker
        assert "notes.md" in label


# =============================================================================
# 3. All 4 v1.18.6 kinds wired with all 3 projectors (sentinel)
# =============================================================================


class TestAllKindsWired:
    """Every artifact kind that ArtifactRegistry knows about MUST also
    be registered with every projector subclass that should support it.
    Sentinel — catches a forgotten registration on a future kind addition."""

    EXPECTED_KINDS = {"image", "pdf", "office", "text"}

    def test_context_attachment_projector_has_all_kinds(self):
        registered = set(ContextAttachmentProjector.list_kinds())
        assert self.EXPECTED_KINDS.issubset(registered), (
            f"Missing context-attachment projections for: "
            f"{self.EXPECTED_KINDS - registered}"
        )

    def test_text_marker_projector_has_all_kinds(self):
        registered = set(TextMarkerProjector.list_kinds())
        assert self.EXPECTED_KINDS.issubset(registered), (
            f"Missing text-marker projections for: "
            f"{self.EXPECTED_KINDS - registered}"
        )

    def test_message_box_projector_has_all_kinds(self):
        registered = set(MessageBoxProjector.list_kinds())
        assert self.EXPECTED_KINDS.issubset(registered), (
            f"Missing message-box projections for: "
            f"{self.EXPECTED_KINDS - registered}"
        )


# =============================================================================
# 4. Strict-by-default + project_optional() forward-compat
# =============================================================================


class TestStrictAndOptional:
    """project() is strict — KeyError on unknown kind. project_optional()
    is the forward-compat variant that returns None silently."""

    def test_unknown_kind_raises_keyerror(self):
        @dataclass
        class _UnknownRef:
            kind: str = "future_subagent_plan"

        ref = _UnknownRef()
        with pytest.raises(KeyError, match="future_subagent_plan"):
            ContextAttachmentProjector.project(ref)

    def test_unknown_kind_returns_none_in_optional(self):
        @dataclass
        class _UnknownRef:
            kind: str = "future_subagent_plan"

        ref = _UnknownRef()
        assert ContextAttachmentProjector.project_optional(ref) is None

    def test_missing_kind_attribute_returns_none_in_optional(self):
        """project_optional() defends against malformed ref objects too."""
        class _NoKind:
            pass

        assert ContextAttachmentProjector.project_optional(_NoKind()) is None

    def test_keyerror_message_includes_registered_kinds(self):
        """Diagnostic — the KeyError message names the available kinds
        so the developer who hits it knows where to add the registration."""
        @dataclass
        class _UnknownRef:
            kind: str = "mystery"

        with pytest.raises(KeyError) as exc_info:
            TextMarkerProjector.project(_UnknownRef())
        msg = str(exc_info.value)
        assert "image" in msg
        assert "TextMarkerProjector" in msg


# =============================================================================
# 5. Registration semantics
# =============================================================================


class TestRegistrationSemantics:
    """Empty kind / collision / idempotent same-handler — same rules
    as ArtifactRegistry, mirrored here so projector wiring has the
    same guardrails as the kind-class registry."""

    def test_empty_kind_raises(self):
        with pytest.raises(ValueError, match="non-empty string"):
            ContextAttachmentProjector.register("")

    def test_idempotent_same_handler_no_op(self):
        """Re-decorating the SAME handler object with the SAME kind on
        the SAME projector is a no-op (supports module reload in tests
        where the imported handler identity is preserved). NB: this
        is identity-based (`existing is handler`), NOT name-based — a
        `def` with the same name in the same scope creates a new
        function object and IS treated as a collision."""

        class _TestProjector(ArtifactProjector):
            pass

        def _h(ref):
            return ref

        _TestProjector.register("dup")(_h)
        # Decorating the EXACT SAME function object is a no-op
        _TestProjector.register("dup")(_h)
        assert "dup" in _TestProjector.list_kinds()

    def test_collision_with_different_handler_raises(self):
        """Registering a DIFFERENT handler under the same kind is a
        collision and must raise."""

        class _CollisionProjector(ArtifactProjector):
            pass

        @_CollisionProjector.register("conflict")
        def _h1(ref):
            return "h1"

        with pytest.raises(ValueError, match="already registered"):

            @_CollisionProjector.register("conflict")
            def _h2(ref):
                return "h2"


# =============================================================================
# 6. Per-kind projection contract — pin output shape so consumers can rely on it
# =============================================================================


class TestProjectionOutputShape:
    """Lock the output shape of every (projector, kind) pair so
    Step 7b consumers can swap in projector calls without surprise.
    These pin the same fields readers used to build by hand."""

    def test_image_context_dto_shape(self):
        ref = ImageAttachmentRef(
            block_index=0, name="x.png", file_id="fid",
            media_type="image/png",
        )
        dto = ContextAttachmentProjector.project(ref)
        assert set(dto.keys()) == {"name", "kind", "media_type", "file_id"}
        assert dto["kind"] == "image"

    def test_pdf_context_dto_uses_pdf_kind(self):
        ref = PdfAttachmentRef(
            block_index=0, name="doc.pdf", file_id="fid",
            media_type="application/pdf",
        )
        dto = ContextAttachmentProjector.project(ref)
        assert dto["kind"] == "pdf"

    def test_office_context_dto_uses_file_kind(self):
        """Office docs project as kind="file" today — preserves the
        pre-Step-7 multimodal_ops mapping. UI can promote to "office"
        in a future iteration once renderers learn it."""
        ref = OfficeAttachmentRef(
            block_index=0, name="sheet.xlsx", file_id="fid",
            media_type="application/vnd.ms-excel",
        )
        dto = ContextAttachmentProjector.project(ref)
        assert dto["kind"] == "file"

    def test_text_context_dto_uses_file_kind(self):
        """Text artifacts also project as kind="file" — matches the
        pre-Step-7 `<uploaded_file>` text-marker branch in multimodal_ops."""
        ref = TextAttachmentRef(
            block_index=0, name="notes.md", file_id="fid",
            media_type="text/markdown",
        )
        dto = ContextAttachmentProjector.project(ref)
        assert dto["kind"] == "file"

    def test_image_text_marker_format(self):
        ref = ImageAttachmentRef(block_index=0, name="x.png", file_id="")
        assert TextMarkerProjector.project(ref) == "[Image: x.png]"

    def test_pdf_text_marker_includes_page_count_when_known(self):
        with_pages = PdfAttachmentRef(
            block_index=0, name="doc.pdf", file_id="", page_count=10,
        )
        without_pages = PdfAttachmentRef(
            block_index=0, name="other.pdf", file_id="", page_count=None,
        )
        assert "10 pages" in TextMarkerProjector.project(with_pages)
        assert "pages" not in TextMarkerProjector.project(without_pages)

    def test_office_and_text_share_attached_marker_shape(self):
        office = OfficeAttachmentRef(block_index=0, name="s.xlsx", file_id="")
        text = TextAttachmentRef(block_index=0, name="n.md", file_id="")
        assert TextMarkerProjector.project(office) == "[Attached: s.xlsx]"
        assert TextMarkerProjector.project(text) == "[Attached: n.md]"

    def test_message_box_labels_are_non_empty_strings(self):
        """Light contract — every kind produces something the message-box
        widget can display. Specific glyphs are renderer-impl detail."""
        for ref in [
            ImageAttachmentRef(block_index=0, name="a.png", file_id=""),
            PdfAttachmentRef(block_index=0, name="b.pdf", file_id=""),
            OfficeAttachmentRef(block_index=0, name="c.xlsx", file_id=""),
            TextAttachmentRef(block_index=0, name="d.md", file_id=""),
        ]:
            label = MessageBoxProjector.project(ref)
            assert isinstance(label, str)
            assert len(label) > 0
            assert ref.name in label


# =============================================================================
# 7. has_kind / list_kinds discoverability
# =============================================================================


class TestDiscoverability:
    """has_kind / list_kinds mirror Renderer.has_renderer / list_registered_types."""

    def test_has_kind_returns_true_for_registered(self):
        assert ContextAttachmentProjector.has_kind("image") is True
        assert TextMarkerProjector.has_kind("pdf") is True

    def test_has_kind_returns_false_for_unregistered(self):
        assert ContextAttachmentProjector.has_kind("future_kind") is False

    def test_list_kinds_returns_sorted(self):
        kinds = ContextAttachmentProjector.list_kinds()
        assert kinds == sorted(kinds)
        assert "image" in kinds
        assert "pdf" in kinds


# =============================================================================
# 8. Pattern parity sentinel — projector model matches Renderer's
# =============================================================================


class TestPatternParityWithRenderer:
    """Sentinel: ArtifactProjector's per-subclass _registry model must
    use the same `cls.__dict__['_registry']` mechanism as
    `rendering/base.py::Renderer`. If the Renderer pattern changes, this
    test surfaces the divergence so the projector framework can stay
    aligned."""

    def test_projector_uses_dict_lookup_for_registry(self):
        """Like Renderer, ArtifactProjector reads its registry via
        cls.__dict__.get('_registry', {}) so subclass state is isolated."""
        # ContextAttachmentProjector has its own _registry in __dict__
        assert "_registry" in ContextAttachmentProjector.__dict__

    def test_projector_subclass_inheritance_does_not_share_state(self):
        """A subclass of ContextAttachmentProjector (e.g. for an
        experimental projector variant) must NOT see ContextAttachmentProjector's
        registrations as its own. Same isolation Renderer enforces."""

        class _ExtendedCtxProjector(ContextAttachmentProjector):
            pass

        # Before any registration, the subclass has its OWN empty registry
        # (or no _registry key at all in __dict__)
        ext_registry = _ExtendedCtxProjector.__dict__.get("_registry", {})
        assert ext_registry == {}

        # Registering on the subclass populates ITS registry, not the parent's
        @_ExtendedCtxProjector.register("custom")
        def _h(ref):
            return "extended"

        assert "custom" in _ExtendedCtxProjector.list_kinds()
        assert "custom" not in ContextAttachmentProjector.list_kinds()
