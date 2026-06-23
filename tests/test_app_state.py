"""Tests for AppState — canonical observable application state."""

import threading

import pytest

from ppxai.engine.app_state import AppState


class TestAppStateBasics:
    """Core get/set/default behavior."""

    def test_defaults(self):
        state = AppState()
        assert state.get("provider") == ""
        assert state.get("model") == ""
        assert state.get("tools_enabled") is False
        assert state.get("is_streaming") is False
        assert state.get("total_tokens") == 0
        assert state.get("estimated_cost") == 0.0

    def test_initial_values(self):
        state = AppState(initial={"provider": "openai", "model": "gpt-4.1-mini"})
        assert state.get("provider") == "openai"
        assert state.get("model") == "gpt-4.1-mini"
        # Non-overridden fields keep defaults
        assert state.get("tools_enabled") is False

    def test_initial_ignores_unknown_fields(self):
        state = AppState(initial={"provider": "openai", "unknown_field": "ignored"})
        assert state.get("provider") == "openai"
        assert state.get("unknown_field") is None

    def test_set_returns_true_on_change(self):
        state = AppState()
        assert state.set("provider", "perplexity") is True

    def test_set_returns_false_on_noop(self):
        state = AppState(initial={"provider": "perplexity"})
        assert state.set("provider", "perplexity") is False

    def test_set_returns_false_for_unknown_field(self):
        state = AppState()
        assert state.set("not_a_field", "value") is False

    def test_get_after_set(self):
        state = AppState()
        state.set("provider", "gemini")
        assert state.get("provider") == "gemini"

    def test_set_various_types(self):
        state = AppState()
        state.set("tools_enabled", True)
        assert state.get("tools_enabled") is True

        state.set("total_tokens", 1500)
        assert state.get("total_tokens") == 1500

        state.set("estimated_cost", 0.0042)
        assert state.get("estimated_cost") == 0.0042

        state.set("working_dir", "/home/user/project")
        assert state.get("working_dir") == "/home/user/project"


class TestAppStateObservers:
    """Observer pattern — on(), off(), listener dispatch."""

    def test_listener_called_on_change(self):
        state = AppState()
        values = []
        state.on("provider", lambda v: values.append(v))
        state.set("provider", "openai")
        assert values == ["openai"]

    def test_listener_not_called_on_noop(self):
        state = AppState(initial={"provider": "openai"})
        values = []
        state.on("provider", lambda v: values.append(v))
        state.set("provider", "openai")  # same value
        assert values == []

    def test_multiple_listeners(self):
        state = AppState()
        a, b = [], []
        state.on("model", lambda v: a.append(v))
        state.on("model", lambda v: b.append(v))
        state.set("model", "sonar-pro")
        assert a == ["sonar-pro"]
        assert b == ["sonar-pro"]

    def test_listeners_on_different_fields(self):
        state = AppState()
        providers, models = [], []
        state.on("provider", lambda v: providers.append(v))
        state.on("model", lambda v: models.append(v))
        state.set("provider", "openai")
        state.set("model", "gpt-4.1-mini")
        assert providers == ["openai"]
        assert models == ["gpt-4.1-mini"]

    def test_on_returns_self_for_chaining(self):
        state = AppState()
        result = state.on("provider", lambda v: None)
        assert result is state

    def test_off_removes_listener(self):
        state = AppState()
        values = []
        fn = lambda v: values.append(v)
        state.on("provider", fn)
        state.set("provider", "openai")
        assert values == ["openai"]

        state.off("provider", fn)
        state.set("provider", "gemini")
        assert values == ["openai"]  # no new value

    def test_off_unknown_listener_is_safe(self):
        state = AppState()
        state.off("provider", lambda v: None)  # no error

    def test_off_returns_self_for_chaining(self):
        state = AppState()
        result = state.off("provider", lambda v: None)
        assert result is state


class TestAppStateBatchUpdate:
    """Batch update — multiple fields atomically."""

    def test_update_multiple_fields(self):
        state = AppState()
        state.update(provider="openai", model="gpt-4.1-mini", tools_enabled=True)
        assert state.get("provider") == "openai"
        assert state.get("model") == "gpt-4.1-mini"
        assert state.get("tools_enabled") is True

    def test_update_fires_listeners_after_all_mutations(self):
        state = AppState()
        snapshots = []

        def capture_provider(v):
            # When provider listener fires, model should already be set
            snapshots.append(state.snapshot())

        state.on("provider", capture_provider)
        state.update(provider="openai", model="gpt-4.1-mini")

        assert snapshots[0]["provider"] == "openai"
        assert snapshots[0]["model"] == "gpt-4.1-mini"  # both set before dispatch

    def test_update_skips_unchanged_fields(self):
        state = AppState(initial={"provider": "openai", "model": "gpt-4"})
        values = []
        state.on("provider", lambda v: values.append(("provider", v)))
        state.on("model", lambda v: values.append(("model", v)))

        state.update(provider="openai", model="gpt-4.1-mini")  # only model changed
        assert values == [("model", "gpt-4.1-mini")]

    def test_update_ignores_unknown_fields(self):
        state = AppState()
        state.update(provider="openai", bogus="ignored")
        assert state.get("provider") == "openai"
        assert state.get("bogus") is None


class TestAppStateSnapshot:
    """Snapshot for debugging/serialization."""

    def test_snapshot_returns_copy(self):
        state = AppState(initial={"provider": "openai"})
        snap = state.snapshot()
        snap["provider"] = "modified"
        assert state.get("provider") == "openai"  # original unchanged

    def test_snapshot_has_all_fields(self):
        state = AppState()
        snap = state.snapshot()
        for key in AppState.FIELDS:
            assert key in snap


class TestAppStateThreadSafety:
    """Concurrent access must not corrupt state."""

    def test_concurrent_writes(self):
        state = AppState()
        errors = []

        def writer(n):
            try:
                for i in range(100):
                    state.set("total_tokens", n * 100 + i)
                    state.get("total_tokens")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=writer, args=(t,)) for t in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == []
        # Final value should be from one of the writers
        assert isinstance(state.get("total_tokens"), int)

    def test_concurrent_update_and_observe(self):
        state = AppState()
        values = []
        state.on("provider", lambda v: values.append(v))

        def writer():
            for p in ["a", "b", "c", "d", "e"]:
                state.set("provider", p)

        threads = [threading.Thread(target=writer) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # All callbacks should have been called (no crashes)
        assert len(values) > 0
        # Final value should be one of the written values
        assert state.get("provider") in ["a", "b", "c", "d", "e"]


class TestAppStateFieldCoverage:
    """Verify all canonical fields exist and have correct default types."""

    def test_all_fields_have_defaults(self):
        state = AppState()
        for key, default in AppState.FIELDS.items():
            value = state.get(key)
            assert value == default, f"{key}: expected {default!r}, got {value!r}"
            assert type(value) == type(default), f"{key}: expected {type(default)}, got {type(value)}"

    def test_field_count(self):
        # Catch accidental field removal. Bump this when adding new canonical
        # state fields — the number is intentional friction so additions get
        # reviewed against the cross-client (Python/JS/TS) schema.
        # v1.17.4: schema-driven from app_state_schema.json; 18 fields total.
        # v1.18.0 P0:   +`agent_beat` for agent heartbeat state → 19.
        # v1.18.0 Ph3: +`last_message_role` for alternation checks → 20.
        # v1.18.6:     +`model_supports_vision` drives attach-button
        #              badge + per-file warning when image attached to
        #              non-vision model → 21.
        # v1.19.0 Inc9: +`background_agents` active-run mirror for the
        #              UI badge that survives reconnect → 22.
        assert len(AppState.FIELDS) == 22

    def test_mutable_defaults_not_shared_between_instances(self):
        """Each AppState instance must get its own copy of list/dict
        defaults. Otherwise mutating `context_attachments` on one
        instance would leak into another (classic Python mutable-default
        bug that the schema loader has to handle carefully)."""
        a = AppState()
        b = AppState()
        # Both start empty
        assert a.get("context_attachments") == []
        assert b.get("context_attachments") == []
        # Mutate a's list directly
        a.get("context_attachments").append({"name": "x.png"})
        # b must remain empty
        assert b.get("context_attachments") == []


class TestSchemaDTO:
    """Pin invariants on the canonical AppState schema file.

    `ppxai/engine/app_state_schema.json` is the golden source of
    truth for cross-language state field definitions — Python loads
    it at module import, the Web client reads it via
    `window.APP_STATE_SCHEMA` injected into `index.html` by the
    FastAPI static route, and the VSCode extension bundles a copy
    at `vscode-extension/resources/app-state-schema.json` kept in
    sync by `scripts/sync-schema.js`.

    These tests verify the schema file itself is well-formed and
    that the bundled VSCode copy matches the canonical source
    byte-for-byte.
    """

    @property
    def schema(self) -> dict:
        """The canonical schema, loaded by AppState at module import."""
        return AppState.SCHEMA

    @property
    def canonical_path(self):
        import pathlib
        return (
            pathlib.Path(__file__).parent.parent
            / "ppxai" / "engine" / "app_state_schema.json"
        )

    @property
    def vscode_bundled_path(self):
        import pathlib
        return (
            pathlib.Path(__file__).parent.parent
            / "vscode-extension" / "resources" / "app-state-schema.json"
        )

    def test_schema_has_version(self):
        assert "version" in self.schema
        assert isinstance(self.schema["version"], str)

    def test_schema_has_fields_dict(self):
        assert "fields" in self.schema
        assert isinstance(self.schema["fields"], dict)
        # Bump when adding fields — keep in sync with test_field_count above.
        # v1.18.6: +`model_supports_vision` → 21.
        # v1.19.0 Inc9: +`background_agents` → 22.
        assert len(self.schema["fields"]) == 22

    def test_schema_fields_match_app_state_fields(self):
        """Every schema field must appear in AppState.FIELDS with the
        same default value. The `AppState.FIELDS` dict is derived from
        the schema, so this is really asserting that the derivation
        logic works correctly for every field."""
        for name, spec in self.schema["fields"].items():
            assert name in AppState.FIELDS
            assert AppState.FIELDS[name] == spec["default"]

    def test_every_field_has_required_properties(self):
        """Every field entry must declare client, type, default, and group."""
        required = {"client", "type", "default", "group"}
        for name, spec in self.schema["fields"].items():
            missing = required - set(spec.keys())
            assert not missing, f"field '{name}' missing properties: {missing}"

    def test_field_types_are_valid(self):
        """Each `type` must be one of the JSON-schema-ish types we support."""
        allowed = {"string", "boolean", "integer", "number", "array", "object"}
        for name, spec in self.schema["fields"].items():
            assert spec["type"] in allowed, (
                f"field '{name}' has unknown type '{spec['type']}'. "
                f"Allowed: {sorted(allowed)}"
            )

    def test_field_defaults_match_declared_type(self):
        """The `default` value must match the declared `type`."""
        type_checks = {
            "string":  lambda v: isinstance(v, str),
            "boolean": lambda v: isinstance(v, bool),
            "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
            "number":  lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
            "array":   lambda v: isinstance(v, list),
            "object":  lambda v: isinstance(v, dict),
        }
        for name, spec in self.schema["fields"].items():
            check = type_checks[spec["type"]]
            assert check(spec["default"]), (
                f"field '{name}' declares type '{spec['type']}' but "
                f"default is {spec['default']!r} ({type(spec['default']).__name__})"
            )

    def test_field_names_are_snake_case(self):
        """Every top-level field name must be valid snake_case so the
        client facades can translate via a simple 1:1 map."""
        import re
        pattern = re.compile(r"^[a-z][a-z0-9]*(_[a-z0-9]+)*$")
        for name in self.schema["fields"]:
            assert pattern.match(name), (
                f"field name '{name}' is not clean snake_case. "
                f"Expected pattern: ^[a-z][a-z0-9]*(_[a-z0-9]+)*$"
            )

    def test_client_names_are_camel_case(self):
        """Every `client` name must be valid camelCase for JS/TS."""
        import re
        pattern = re.compile(r"^[a-z][a-zA-Z0-9]*$")
        for name, spec in self.schema["fields"].items():
            assert pattern.match(spec["client"]), (
                f"field '{name}' has non-camelCase client name "
                f"'{spec['client']}'. Expected pattern: ^[a-z][a-zA-Z0-9]*$"
            )

    def test_vscode_bundled_copy_matches_canonical(self):
        """The VSCode extension bundles a copy of the schema at
        `vscode-extension/resources/app-state-schema.json`, kept in
        sync by `scripts/sync-schema.js` (run by the precompile hook).

        This test asserts byte-for-byte equality — if someone edits
        one without updating the other, CI fails here and points at
        the fix (`npm run sync-schema` from the extension directory).
        """
        assert self.canonical_path.exists(), (
            f"canonical schema missing at {self.canonical_path}"
        )
        assert self.vscode_bundled_path.exists(), (
            f"VSCode bundled schema missing at {self.vscode_bundled_path}. "
            f"Run 'npm run sync-schema' from vscode-extension/ to create it."
        )
        canonical = self.canonical_path.read_bytes()
        bundled = self.vscode_bundled_path.read_bytes()
        assert canonical == bundled, (
            f"VSCode bundled schema is out of sync with canonical source. "
            f"Run 'npm run sync-schema' from vscode-extension/ to fix."
        )

    def test_schema_round_trips_through_json(self):
        """Sanity check: the schema serializes and parses back to
        itself. Catches accidental non-JSON-serializable values that
        would break the server endpoint and HTML injection."""
        import json
        serialized = json.dumps(self.schema)
        reloaded = json.loads(serialized)
        assert reloaded == self.schema

    def test_python_tui_state_access_uses_schema_fields_only(self):
        """Pin that the Rich (`ppxai`) and Textual (`ppxaide`) TUIs
        only access state fields that are declared in the canonical
        schema. Scans the TUI source files for
        `engine_client.state.get/on/set("<name>")` and
        `state.get/on/set("<name>")` calls and asserts every captured
        `<name>` is a field in `AppState.SCHEMA["fields"]`.

        Note: `last_state.get(...)` calls (session recovery dicts from
        `SessionManager.get_last_session_state()`) are NOT AppState
        access and are filtered out via a negative lookbehind on the
        regex. Adding a new hardcoded TUI field that isn't declared in
        the schema will fail this test, pointing at the drift.
        """
        import re
        import pathlib

        repo_root = pathlib.Path(__file__).parent.parent
        tui_sources = [
            repo_root / "ppxai" / "rich" / "main.py",
            repo_root / "ppxai" / "rich" / "event_handler.py",
            repo_root / "ppxai" / "tui" / "app.py",
            repo_root / "ppxai" / "tui" / "stream_handler.py",
        ]

        # Match `<prefix>state.get/on/set("field")` where prefix is
        # either empty or `engine_client.` / `self._engine_client.` /
        # `self.state` / the start of a line. Crucially, we exclude
        # `last_state.get(...)` and `session_state.get(...)` which are
        # session recovery dicts, not AppState.
        pattern = re.compile(
            r'(?<![_a-zA-Z])state\.(?:get|on|set)\s*\(\s*["\']([a-z_]+)["\']'
        )

        schema_fields = set(AppState.SCHEMA["fields"].keys())
        all_violations: list[tuple[pathlib.Path, str]] = []

        for source in tui_sources:
            if not source.exists():
                continue
            content = source.read_text(encoding="utf-8")
            # Line-by-line so we can skip lines that clearly reference
            # session recovery dicts (last_state, session_state).
            for line in content.splitlines():
                # Skip session recovery dict reads
                if "last_state" in line or "session_state" in line:
                    continue
                for match in pattern.finditer(line):
                    field = match.group(1)
                    if field not in schema_fields:
                        all_violations.append((source, field))

        assert not all_violations, (
            "Python TUI (Rich/Textual) accesses AppState fields that are "
            "not declared in the canonical schema — add them to "
            "ppxai/engine/app_state_schema.json or remove the access:\n"
            + "\n".join(
                f"  {source.relative_to(repo_root)}: '{field}'"
                for source, field in all_violations
            )
        )


class TestSseSyncFieldsContract:
    """Pin the engine → web/VSCode state_sync contract.

    Adding a field to `_SSE_SYNC_FIELDS` in `ppxai/engine/client.py`
    means the web and VSCode clients receive it via SSE `state_sync`
    events. Both clients ingest those payloads through the AppState
    facade (`ppxai/web/shared/app-state.js::AppState.updateFromPython`
    and `vscode-extension/src/appState.ts::AppState.updateFromPython`),
    which translates snake_case → camelCase via a schema-derived map
    built from `ppxai/engine/app_state_schema.json` at startup.

    Since v1.17.4 the facades are schema-driven — they build their
    translation table dynamically from the canonical JSON. These
    tests pin the engine-side invariants that keep that wiring valid:

    1. Every field in `_SSE_SYNC_FIELDS` must exist in the canonical
       schema (no orphaned sync fields that reference nothing).
    2. Every field must be clean snake_case so the client facades
       can treat the mapping as a simple 1:1 table.
    3. The field count matches the documented whitelist size.
    """

    @property
    def sse_sync_fields(self) -> frozenset:
        """Return the engine's SSE sync whitelist.

        v1.18.0: the set is now a module-level constant
        (`SSE_SYNC_FIELDS`) in `ppxai/engine/client.py` so the
        `GET /state` endpoint can return the same shape. Previously
        extracted via AST from a local variable inside __init__.
        """
        from ppxai.engine.client import SSE_SYNC_FIELDS

        return frozenset(SSE_SYNC_FIELDS)

    def test_all_sync_fields_exist_in_app_state(self):
        """No orphaned sync fields — every pushed field must be a real AppState key."""
        for field in self.sse_sync_fields:
            assert field in AppState.FIELDS, (
                f"_SSE_SYNC_FIELDS contains '{field}' but AppState.FIELDS "
                f"has no such key. Either add it to AppState.FIELDS or "
                f"remove it from the whitelist in engine/client.py."
            )

    def test_all_sync_fields_are_snake_case(self):
        """Clean snake_case so the web/VSCode facade maps stay 1:1."""
        import re
        pattern = re.compile(r"^[a-z][a-z0-9]*(_[a-z0-9]+)*$")
        for field in self.sse_sync_fields:
            assert pattern.match(field), (
                f"_SSE_SYNC_FIELDS entry '{field}' is not clean snake_case. "
                f"The web/VSCode AppState facades map each snake_case key "
                f"to a camelCase field via a static `PYTHON_TO_JS` / "
                f"`PYTHON_TO_TS` record; entries must match "
                f"`^[a-z][a-z0-9]*(_[a-z0-9]+)*$` so the mapping is "
                f"trivially 1:1 — no leading uppercase, no leading digits, "
                f"no consecutive underscores."
            )

    def test_sync_field_count(self):
        """Pin the whitelist size. Bump this when adding a new
        cross-client sync field to `_SSE_SYNC_FIELDS`. The client
        AppState facades pick up schema additions automatically —
        the only thing to update besides the engine is this count.

        Current entries:
            v1.18.0: provider, model, tools_enabled, tools_verbose,
                agent_mode, auto_route, working_dir, session_name,
                debug_log, context_attachments, agent_beat (P0).
            v1.18.6: +model_supports_vision → 12.
            v1.19.0 Inc9: +background_agents → 13.
        """
        assert len(self.sse_sync_fields) == 13

    def test_sync_fields_have_client_names_in_schema(self):
        """Every sync field must declare a `client` name in the
        canonical schema. The client facades look up each snake_case
        key in that schema-derived map — a field in `_SSE_SYNC_FIELDS`
        with no schema entry would fall into the drift warning path."""
        for field in self.sse_sync_fields:
            assert field in AppState.SCHEMA["fields"], (
                f"_SSE_SYNC_FIELDS entry '{field}' is missing from "
                f"ppxai/engine/app_state_schema.json. Add it to the "
                f"schema (with a `client` camelCase name) so the web "
                f"and VSCode facades can translate it."
            )
            client = AppState.SCHEMA["fields"][field]["client"]
            assert isinstance(client, str) and client, (
                f"_SSE_SYNC_FIELDS entry '{field}' has an empty or "
                f"invalid `client` name in the schema: {client!r}"
            )
