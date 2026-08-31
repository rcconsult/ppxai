"""ArtifactRegistry — kind-discriminated dispatch for MarshallableArtifact.

ADR 0006 Foundation (v1.18.6). Cross-process schema interop primitive
that enables `Message.attachments` to round-trip through v2 session
JSON (Step 4), v1.19.x agent-run state.json (per ADR 0003), ADR 0005
events.jsonl, and any future persisted-artifact channel — without any
consumer needing to know every artifact kind upfront.

Pattern alignment with `ppxai/rendering/base.py::Renderer`
==========================================================

This registry mirrors the existing CommandResult renderer dispatch:

| Concern              | Renderer                       | ArtifactRegistry          |
|----------------------|--------------------------------|---------------------------|
| Registration style   | Decorator @cls.register(...)   | Decorator @cls.register(kind) |
| Registry key         | Type[CommandResult] (class)    | str (discriminator)       |
| Registry value       | Callable (handler function)    | Type[MarshallableArtifact]|
| Dispatch entry       | render(result)                 | deserialize(data)         |
| Discoverability      | has_renderer / list_registered | has_kind / list_registered_kinds |
| Subclass isolation   | Per-subclass _registry via __dict__ | Single registry (one global truth source per kind) |
| Fallback chain       | MRO walk → TextResult fallback | None (kind dispatch is exact)|
| Sync/async variants  | Renderer + AsyncRenderer       | None (deserialize is sync) |

The two registries solve different problems but use the same
architectural style: decorator-based registration, mechanical
discriminator dispatch, no if/elif chains anywhere. Adding a new
artifact kind = decorate a new dataclass with `@ArtifactRegistry.register("foo")`.
Adding a new renderer for an existing kind doesn't apply here —
artifact deserialization has exactly one canonical class per kind.

Cross-process safety
--------------------

Registration happens at module import time (single-threaded by
Python's import lock). The registry dict is read-only after module
init — `deserialize` only reads. No locks needed at runtime.

If a future use case requires runtime kind registration (e.g. plugins
loaded after startup), add an explicit registration mutex; today's
static-at-import model is sufficient and avoids per-deserialize lock
acquisition.

Why a global registry, not per-subclass like Renderer
-----------------------------------------------------

Renderer needs per-subclass registries because RichRenderer and
TextualRenderer register DIFFERENT handlers for the same result type.
ArtifactRegistry has exactly ONE class per kind globally — there's no
analog to "Rich's view of an ImageAttachmentRef" vs "Textual's view".
Cross-process dispatch needs a single source of truth for kind→class.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, TypeVar

from ..common.logger import get_logger
from .types import MarshallableArtifact

logger = get_logger("engine")


# Subclass of MarshallableArtifact — keeps decorator type hints clean.
M = TypeVar("M", bound=MarshallableArtifact)


class ArtifactRegistry:
    """kind → MarshallableArtifact class registry.

    Use the decorator at the class definition site:

        @ArtifactRegistry.register("image")
        @dataclass
        class ImageAttachmentRef:
            SCHEMA_VERSION: ClassVar[int] = 1
            block_index: int
            name: str
            ...
            def to_dict(self) -> Dict[str, Any]: ...
            @classmethod
            def from_dict(cls, data) -> "ImageAttachmentRef": ...

    Cross-process readers consume serialized artifacts via the class
    method `deserialize(data)`:

        ref = ArtifactRegistry.deserialize({"kind": "image",
                                            "_schema_version": 1,
                                            "block_index": 0,
                                            "name": "x.png", ...})
        # → ImageAttachmentRef(block_index=0, name="x.png", ...)

    Class methods (not instance methods) — there's only ever one
    registry per process. Stateless dispatch.
    """

    _registry: dict[str, type[MarshallableArtifact]] = {}
    """kind string → concrete MarshallableArtifact class.
    Filled at import time as each artifact dataclass is decorated.
    Read-only after init; cross-thread safe by construction."""

    @classmethod
    def register(cls, kind: str) -> Callable[[type[M]], type[M]]:
        """Decorator — register a MarshallableArtifact class for the given kind.

        Args:
            kind: Discriminator string. Must be non-empty, lowercase
                snake_case, globally unique within ppxai. Convention
                matches the `kind` field's value on the registered class.

        Returns:
            The unchanged class. Decorator is identity on the class
            object — registration is the side effect.

        Raises:
            ValueError: kind is empty or already registered to a
                different class. Re-decorating the SAME class with
                the same kind is a no-op (supports module reload in
                tests / dev).

        Example:
            @ArtifactRegistry.register("image")
            @dataclass
            class ImageAttachmentRef:
                ...
        """
        if not kind:
            raise ValueError(
                "ArtifactRegistry.register: kind must be a non-empty string"
            )

        def decorator(target: type[M]) -> type[M]:
            existing = cls._registry.get(kind)
            if existing is not None and existing is not target:
                raise ValueError(
                    f"ArtifactRegistry.register: kind={kind!r} already "
                    f"registered to {existing.__name__!r}; refusing to "
                    f"silently override with {target.__name__!r}. Use "
                    f"distinct kind strings — no namespace collision allowed."
                )
            cls._registry[kind] = target
            return target

        return decorator

    @classmethod
    def deserialize(cls, data: dict[str, Any]) -> MarshallableArtifact | None:
        """Reconstruct an artifact from its serialized dict via kind dispatch.

        Reads `data["kind"]`, looks up the registered class, calls
        `cls.from_dict(data)`. Returns None for unknown kinds so loaders
        can skip artifacts they don't understand without crashing —
        forward-compat property required by ADR 0003 (agent runs may
        contain newer-version artifact kinds an older ppxai doesn't
        recognize).

        Args:
            data: The dict produced by some MarshallableArtifact's
                `to_dict()`. Must include a "kind" key. Other required
                fields are kind-specific and validated by `from_dict`.

        Returns:
            Reconstructed concrete artifact (whose runtime type is the
            class registered for `data["kind"]`), OR None when:
              - data is not a dict
              - data has no "kind" field
              - kind is not registered (newer-version artifact unknown
                to this build)

            Per-kind `from_dict` raises on data shape errors (missing
            required fields, version too new); those propagate because
            they indicate genuine data corruption, not just "this build
            doesn't know this kind yet".
        """
        if not isinstance(data, dict):
            logger.warning(
                f"ArtifactRegistry.deserialize: expected dict, "
                f"got {type(data).__name__}"
            )
            return None
        kind = data.get("kind")
        if not kind:
            logger.warning(
                f"ArtifactRegistry.deserialize: missing 'kind' discriminator "
                f"in data: keys={list(data.keys())}"
            )
            return None
        target_cls = cls._registry.get(kind)
        if target_cls is None:
            logger.warning(
                f"ArtifactRegistry.deserialize: unknown kind {kind!r}. Known "
                f"kinds: {sorted(cls._registry.keys())}. Artifact will be "
                f"skipped — upgrade ppxai if this kind is required."
            )
            return None
        return target_cls.from_dict(data)

    @classmethod
    def has_kind(cls, kind: str) -> bool:
        """Check whether a kind has a registered class. Mirrors
        `Renderer.has_renderer(type)` for symmetry with the existing pattern."""
        return kind in cls._registry

    @classmethod
    def list_registered_kinds(cls) -> list[str]:
        """Return the sorted list of currently-registered kind strings.

        Useful for `/doctor` checks, diagnostics, and tests asserting
        that expected kinds are wired up at module-import time.
        Mirrors `Renderer.list_registered_types()` for symmetry.
        """
        return sorted(cls._registry.keys())

    @classmethod
    def class_for_kind(cls, kind: str) -> type[MarshallableArtifact] | None:
        """Look up the registered class for a kind without deserializing.

        Useful when callers need to construct artifacts programmatically
        (e.g. v1.19.x sub-agent code) and want to discover what concrete
        class to instantiate for a given kind string.
        """
        return cls._registry.get(kind)


# Concrete artifact classes register themselves at the bottom of types.py
# (where they're defined). Import-side-effect chain:
#
#   1. types.py defines ImageAttachmentRef, PdfAttachmentRef, etc. and
#      decorates each with @ArtifactRegistry.register("image" / "pdf" / ...)
#      at class-def time.
#   2. Anyone importing this module (artifact_registry) transitively
#      imports types.py, triggering the decorators, populating _registry.
#   3. Subsequent ArtifactRegistry.deserialize calls find the kinds.
#
# Why register-at-types.py instead of register-here: keeps this module's
# import graph minimal (only types.MarshallableArtifact), avoids the
# circular import that would happen if registry imported each concrete
# class directly. The decorator pattern means the registration happens
# at the class's natural definition site.
