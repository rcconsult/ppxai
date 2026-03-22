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
        assert state.get("total_cost") == 0.0

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

        state.set("total_cost", 0.0042)
        assert state.get("total_cost") == 0.0042

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
        # Catch accidental field removal
        assert len(AppState.FIELDS) == 17
