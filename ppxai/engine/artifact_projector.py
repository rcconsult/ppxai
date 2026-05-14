"""ArtifactProjector — per-consumer plug-n-play projection registries.

ADR 0006 Step 7a (v1.18.6). Closes the consumer-side half of the
ArtifactRegistry framework: where ArtifactRegistry handles
class-discovery + serialize/deserialize for kinds, ArtifactProjector
handles consumer-specific projections (DTOs, text markers, UI chips).

Pattern alignment with `ppxai/rendering/base.py::Renderer`
==========================================================

Each consumer is its own ArtifactProjector subclass with its own
per-subclass `_registry`. Concrete artifact kinds register handlers
via decorator at the kind's natural definition site. Consumers
dispatch via `cls.project(ref)` — mechanical kind lookup, zero
if/elif ladders.

| Concern              | Renderer                       | ArtifactProjector             |
|----------------------|--------------------------------|-------------------------------|
| Registration style   | @RichRenderer.register(Cls)    | @ContextAttachmentProjector.register("kind") |
| Registry key         | Type[CommandResult]            | str (artifact kind discriminator) |
| Registry value       | Callable (handler function)    | Callable (projection function)|
| Per-subclass state   | cls.__dict__['_registry']      | cls.__dict__['_registry']     |
| Dispatch entry       | cls.render(result)             | cls.project(ref)              |
| Discoverability      | has_renderer / list_types      | has_kind / list_kinds         |

Why per-subclass registries (not one global registry keyed by
(consumer, kind))
-----------------------------------------------------------------

Each consumer has different lookup needs:
  - `ContextAttachmentProjector` needs `(name, kind, media_type, file_id)`
  - `TextMarkerProjector` needs a single string per kind
  - `MessageBoxProjector` needs a chip-friendly label

Forcing one global registry would couple unrelated projection logic
and prevent consumers from being added without registry-key churn.
The per-subclass model lets a future consumer
(`StateExportProjector`, `AgentArtifactProjector`) appear without
touching any existing consumer's registry — same isolation that
makes RichRenderer + TextualRenderer coexist cleanly.

Cross-process safety
--------------------

Same model as ArtifactRegistry: registration at module import time
under the GIL-protected import lock. Each subclass's `_registry` is
read-only at runtime. No locks needed at dispatch.

Consumer addition workflow
--------------------------

Adding a new consumer (e.g. `WireBlockProjector` in v1.19.x to emit
provider-specific JSON for sub-agent message construction):

1. Define `class WireBlockProjector(ArtifactProjector): pass` (one line)
2. For each artifact kind that should support this consumer, add one
   `@WireBlockProjector.register("image")` decorator at the kind's
   definition site (or in a per-kind projection module)
3. Consumer code calls `WireBlockProjector.project(ref)` — done

No reader edits, no if/elif chains, no isinstance ladders.

Adding a new artifact kind (e.g. SubAgentPlanRef) requires adding
one `@<Projector>.register("subagent_plan")` decorator per consumer
the kind should support. That's 4 decorators today (one per existing
projector). Forgetting one is caught by `project()` raising KeyError —
the dispatch never silently falls through to a wrong handler.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

from ..common.logger import get_logger

logger = get_logger("engine")


class ArtifactProjector:
    """Base per-consumer projection registry.

    Subclasses define a single conceptual projection (e.g. "build the
    context-attachment DTO for this artifact"). Each concrete artifact
    kind registers a handler with each projector subclass it should
    support.

    Per-subclass `_registry` follows the exact same pattern as
    `Renderer._registry`: stored in `cls.__dict__` to prevent the
    base class registry from being shared across subclasses, and
    initialized lazily at first registration.
    """

    _registry: Dict[str, Callable] = {}

    @classmethod
    def register(cls, kind: str) -> Callable[[Callable], Callable]:
        """Decorator — register a projection handler for a kind.

        Args:
            kind: Artifact discriminator string. Must match what
                ArtifactRegistry.register() used for the same kind
                (`"image"`, `"pdf"`, `"office"`, `"text"`, etc.).

        Returns:
            Identity decorator on the target callable. Registration
            is the side effect.

        Raises:
            ValueError: kind is empty or already registered to a
                different callable in this projector. Re-decorating
                the SAME callable with the same kind is a no-op
                (supports module reload in tests / dev).

        Example:
            @ContextAttachmentProjector.register("image")
            def _project_image(ref):
                return {"name": ref.name, "kind": "image",
                        "media_type": ref.media_type,
                        "file_id": ref.file_id}
        """
        if not kind:
            raise ValueError(
                f"{cls.__name__}.register: kind must be a non-empty string"
            )

        def decorator(handler: Callable) -> Callable:
            # Mirror Renderer._registry pattern: per-subclass via
            # cls.__dict__ so subclasses don't share registry state
            # with the ArtifactProjector base or with each other.
            if cls is ArtifactProjector:
                raise TypeError(
                    "Cannot register on ArtifactProjector base class. "
                    "Subclass it (e.g. class FooProjector(ArtifactProjector): pass) "
                    "and register on the subclass."
                )
            if "_registry" not in cls.__dict__:
                cls._registry = {}
            existing = cls._registry.get(kind)
            if existing is not None and existing is not handler:
                raise ValueError(
                    f"{cls.__name__}.register: kind={kind!r} already "
                    f"registered to {existing.__name__!r}; refusing to "
                    f"silently override with {handler.__name__!r}. Use "
                    f"distinct kinds — no namespace collision allowed."
                )
            cls._registry[kind] = handler
            return handler

        return decorator

    @classmethod
    def project(cls, ref: Any) -> Any:
        """Dispatch a projection by ref.kind — MECHANICAL lookup.

        Reads `ref.kind` (every MarshallableArtifact carries it),
        looks up the registered handler in this projector's own
        registry, calls it. No conditional logic.

        Args:
            ref: Any object with a `kind: str` attribute. Today's
                producers populate Message.attachments with
                MarshallableArtifact instances; this method narrows
                to that contract via the .kind read.

        Returns:
            Whatever the registered handler returns. Per-projector
            contract — projector subclasses document their return
            shape in their docstring.

        Raises:
            KeyError: No handler registered for ref.kind in this
                projector. Surfaces wiring gaps loudly — adding a new
                kind requires adding handlers to every projector that
                should support it. Never silently falls through to a
                wrong handler.
            AttributeError: ref doesn't have a .kind attribute. Caller
                is passing the wrong type.
        """
        kind = ref.kind
        own_registry = cls.__dict__.get("_registry", {})
        handler = own_registry.get(kind)
        if handler is None:
            available = sorted(own_registry.keys())
            raise KeyError(
                f"{cls.__name__}.project: no handler registered for "
                f"kind={kind!r}. Registered kinds in this projector: "
                f"{available}. Add @{cls.__name__}.register({kind!r}) "
                f"to the kind's projection module."
            )
        return handler(ref)

    @classmethod
    def has_kind(cls, kind: str) -> bool:
        """Check whether a kind has a registered handler in THIS projector.

        Mirrors `Renderer.has_renderer(type)` for symmetry.
        Useful for graceful-degrade callers that want to skip
        projecting unknown kinds rather than catching KeyError.
        """
        own_registry = cls.__dict__.get("_registry", {})
        return kind in own_registry

    @classmethod
    def list_kinds(cls) -> List[str]:
        """Return the sorted list of currently-registered kinds.

        Mirrors `Renderer.list_registered_types()` for symmetry.
        Used by `/doctor` checks and tests asserting the framework
        is wired up at module-import time.
        """
        own_registry = cls.__dict__.get("_registry", {})
        return sorted(own_registry.keys())

    @classmethod
    def project_optional(cls, ref: Any) -> Optional[Any]:
        """Dispatch if registered; return None silently if not.

        Forward-compat variant of `project()`. Use when a consumer
        wants to gracefully skip artifact kinds it doesn't know how
        to project (e.g. an older ppxai loading a session that
        contains a v1.19.x sub-agent artifact kind whose projector
        wasn't ported back).

        Default for new code: prefer `project()` so wiring gaps are
        loud failures, not silent drops. Use `project_optional` only
        when forward-compat skip is the deliberate, documented behavior.
        """
        kind = getattr(ref, "kind", None)
        if not kind:
            return None
        own_registry = cls.__dict__.get("_registry", {})
        handler = own_registry.get(kind)
        if handler is None:
            return None
        return handler(ref)


# =============================================================================
# Concrete projector subclasses — one per consumer
# =============================================================================
#
# Each subclass declares its conceptual projection. Handlers register
# at module import time from `artifact_projections.py` (per-kind
# projection module that imports each MarshallableArtifact and decorates
# the projection callables). Putting the registrations in a separate
# module keeps this file's import graph minimal — no circular
# dependency on engine/types.py.


class ContextAttachmentProjector(ArtifactProjector):
    """Project an artifact ref → context_attachments DTO entry.

    Used by `engine.multimodal_ops.scan_attachments` to build the
    `context_attachments` AppState field. Each handler returns a dict
    of shape:

        {
            "name": str,         # canonical filename
            "kind": str,         # UI category (e.g. "image", "pdf",
                                 #   "office", "file"; renderers can
                                 #   add subcategories)
            "media_type": str,   # canonical MIME type
            "file_id": str,      # SessionFileStore identifier (or "")
        }

    `turn_index` is added by the caller because it depends on
    surrounding message context, not the artifact itself.
    """


class TextMarkerProjector(ArtifactProjector):
    """Project an artifact ref → single-line text placeholder.

    Used by `engine.types.Message.text_content()` to substitute
    multimodal blocks with token-countable text in logging,
    estimation, and markdown export contexts. Each handler returns
    a string, e.g. `"[Image: shot.png]"` or `"[Attached PDF: doc.pdf]"`.
    """


class MessageBoxProjector(ArtifactProjector):
    """Project an artifact ref → TUI message-box label.

    Used by `tui/widgets/message_box.py` to render attachment chips
    inside the conversation transcript widget. Each handler returns
    a string label suitable for inline display
    (e.g. `"⊞ shot.png"` for images, `"⎙ doc.pdf"` for PDFs).
    """
