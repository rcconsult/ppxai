"""The record a provider facts module exports (ADR 0016 §3).

A leaf module so the per-provider data modules and the package's lookup can
both import it without importing each other.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field

from ...model_facts import ModelFacts
from ...types import ProviderCapabilities


@dataclass(frozen=True)
class ProviderFacts:
    """A provider's class-level facts, readable without loading its SDK.

    The fields carry the names of the class attributes they feed
    (`shipped_model_facts`, `default_capabilities`, `unmeasured_facts`,
    `default_model_for_facts`), so ADR 0012's resolution order is unchanged.
    """

    default_capabilities: ProviderCapabilities
    shipped_model_facts: Mapping[str, ModelFacts] = field(default_factory=dict)
    unmeasured_facts: ModelFacts | None = None
    default_model_for_facts: str | None = None
