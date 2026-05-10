"""Shell-command wrapper framework (v1.18.5).

Public API:

- `Wrapper` — abstract base; subclass for bespoke wrappers.
- `ProbeWrapper`, `AlwaysWrapper` — generic concrete classes covering
  the two common decision strategies.
- `make_wrapper(entry)` — factory that turns a JSON config dict into a
  Wrapper instance.
- `WrapperRegistry` — holds active wrappers; per-call decision and
  composition helpers.
- `get_registry()` / `set_registry()` — lazy singleton + test hook.

The framework's three integration points in the rest of ppxai:

1. Shell tool: `await get_registry().find_first_rewrite(cmd)` before
   spawning. None = run raw; otherwise = run the rewritten form.
2. Tool manager (system prompt): `get_registry().compose_prompt_blocks()`
   yields the markdown to inject under a single section header.
3. Consent classifier: `get_registry().strip_transparent_prefixes(cmd)`
   peels leading wrapper tokens before pattern matching, so safety
   verdicts are invariant under wrapping.
"""

from .base import AlwaysWrapper, ProbeWrapper, Wrapper
from .factory import WrapperConfigError, make_wrapper
from .registry import WrapperRegistry, get_registry, set_registry

__all__ = [
    "Wrapper",
    "ProbeWrapper",
    "AlwaysWrapper",
    "WrapperRegistry",
    "WrapperConfigError",
    "make_wrapper",
    "get_registry",
    "set_registry",
]
