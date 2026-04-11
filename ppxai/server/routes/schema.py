"""
Schema endpoint — serves the canonical AppState JSON schema.

The schema lives in `ppxai/engine/app_state_schema.json` inside the
Python package and is loaded once at module import by
`ppxai.engine.app_state`. This endpoint relays it verbatim so:

- The **Web client** receives it via `window.APP_STATE_SCHEMA` injected
  into `index.html` by the static route (so app-state.js can read it
  synchronously at module load, no fetch round-trip needed).

- The **VSCode extension** receives it via a bundled copy at
  `vscode-extension/resources/app-state-schema.json` which is kept in
  sync with the Python source by a pre-compile script. The extension
  can also fetch this endpoint at runtime for diagnostic purposes.

- **Diagnostic tooling** (CLI scripts, docs generators, tests) can
  always ask the running server "what fields does AppState declare?"
  without needing to import the Python package.

    GET /schema/app-state
    → {"version": "1.0", "description": "...", "fields": {...}}
"""

from fastapi import APIRouter

from ...engine.app_state import SCHEMA

router = APIRouter()


@router.get("/schema/app-state")
async def get_app_state_schema() -> dict:
    """Return the canonical AppState schema as JSON.

    Relays `ppxai.engine.app_state.SCHEMA` verbatim. The schema is
    loaded once at module import (Python side) and never mutates,
    so this handler is effectively a constant-time dict return.
    """
    return SCHEMA
