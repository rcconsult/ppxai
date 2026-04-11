"""Tests for `GET /schema/app-state` — the canonical DTO endpoint.

The Python `AppState` loads its schema from
`ppxai/engine/app_state_schema.json` at module import. The server
route `ppxai/server/routes/schema.py` relays that schema verbatim so
diagnostic tooling (and any future runtime consumer that doesn't
bundle its own copy) can always ask the running server "what fields
does AppState declare?".

The web client doesn't actually call this endpoint — it receives the
schema via HTML injection in `static.py::serve_index`. The VSCode
extension bundles its own copy via `scripts/sync-schema.js`. But
both paths start from the same Python `SCHEMA` constant, so testing
the endpoint verifies the full golden-source-of-truth chain.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from ppxai.engine.app_state import SCHEMA as CANONICAL_SCHEMA
from ppxai.server.http import app


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


HEADERS = {"X-Session-Id": "test-schema-endpoint"}


class TestSchemaEndpoint:
    def test_returns_200(self, client: TestClient):
        resp = client.get("/schema/app-state", headers=HEADERS)
        assert resp.status_code == 200

    def test_content_type_is_json(self, client: TestClient):
        resp = client.get("/schema/app-state", headers=HEADERS)
        assert resp.headers["content-type"].startswith("application/json")

    def test_matches_canonical_schema_bytewise(self, client: TestClient):
        """Endpoint body must match the Python `SCHEMA` constant
        exactly. This verifies the route is a pure relay — no
        accidental transformation, filtering, or version skew."""
        resp = client.get("/schema/app-state", headers=HEADERS)
        assert resp.json() == CANONICAL_SCHEMA

    def test_has_version(self, client: TestClient):
        resp = client.get("/schema/app-state", headers=HEADERS)
        body = resp.json()
        assert "version" in body
        assert isinstance(body["version"], str)
        assert body["version"] == CANONICAL_SCHEMA["version"]

    def test_has_all_canonical_fields(self, client: TestClient):
        resp = client.get("/schema/app-state", headers=HEADERS)
        body = resp.json()
        assert "fields" in body
        assert len(body["fields"]) == len(CANONICAL_SCHEMA["fields"])
        for name in CANONICAL_SCHEMA["fields"]:
            assert name in body["fields"]

    def test_provider_field_has_expected_shape(self, client: TestClient):
        """Spot-check one field to pin the item schema format that
        the JS/TS facades depend on: {client, type, default, group, doc?}."""
        resp = client.get("/schema/app-state", headers=HEADERS)
        provider = resp.json()["fields"]["provider"]
        assert provider["client"] == "currentProvider"
        assert provider["type"] == "string"
        assert provider["default"] == ""
        assert "group" in provider

    def test_context_attachments_has_array_default(self, client: TestClient):
        """The multimodal field must default to an empty array so
        the web client can render `if (attachments.length === 0)`
        without a null check."""
        resp = client.get("/schema/app-state", headers=HEADERS)
        attachments = resp.json()["fields"]["context_attachments"]
        assert attachments["type"] == "array"
        assert attachments["default"] == []
        assert attachments["client"] == "contextAttachments"


class TestSchemaHtmlInjection:
    """The FastAPI static route injects `window.APP_STATE_SCHEMA`
    into every `GET /` response so `shared/app-state.js` can read
    the schema synchronously at module load. These tests verify
    the injection pipeline works end-to-end."""

    def test_index_includes_schema_script(self, client: TestClient):
        resp = client.get("/", headers=HEADERS)
        assert resp.status_code in (200, 404)  # 404 if web UI not installed
        if resp.status_code == 404:
            pytest.skip("Web UI not installed at ~/.ppxai/web/")

        body = resp.text
        assert "window.APP_STATE_SCHEMA" in body
        assert 'id="app-state-schema"' in body

    def test_schema_appears_before_app_state_js(self, client: TestClient):
        """The injected script must come before the `shared/app-state.js`
        tag so the AppState class can read the schema at construction."""
        resp = client.get("/", headers=HEADERS)
        if resp.status_code == 404:
            pytest.skip("Web UI not installed at ~/.ppxai/web/")

        body = resp.text
        schema_idx = body.find("window.APP_STATE_SCHEMA")
        appstate_idx = body.find("shared/app-state.js")
        assert schema_idx >= 0, "APP_STATE_SCHEMA not injected"
        assert appstate_idx >= 0, "shared/app-state.js script tag not found"
        assert schema_idx < appstate_idx, (
            f"APP_STATE_SCHEMA injected AFTER shared/app-state.js "
            f"(schema at {schema_idx}, app-state.js at {appstate_idx}) — "
            f"the AppState class will fail to find the schema on construction"
        )

    def test_injected_schema_is_valid_json(self, client: TestClient):
        """Extract the injected schema JSON from the HTML and verify
        it parses + matches the canonical schema."""
        import json
        import re

        resp = client.get("/", headers=HEADERS)
        if resp.status_code == 404:
            pytest.skip("Web UI not installed at ~/.ppxai/web/")

        body = resp.text
        # Extract the JSON between `window.APP_STATE_SCHEMA = ` and `;</script>`
        match = re.search(
            r"window\.APP_STATE_SCHEMA\s*=\s*(\{.*?\});</script>",
            body,
            re.DOTALL,
        )
        assert match is not None, "Could not find schema assignment in HTML"
        schema_json = match.group(1)
        parsed = json.loads(schema_json)
        assert parsed == CANONICAL_SCHEMA
