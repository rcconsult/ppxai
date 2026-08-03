"""Tests for engine-level CompletionProvider (Task #11, v1.17.4).

Exercises the `complete()` function that all four clients delegate to —
directly for Rich/Textual, via POST /complete for Web/VSCode.

Scope:
    - Slash command completion from CommandFactory
    - Alias resolution + annotation
    - Builtin specials (/quit, /exit)
    - Path argument completion per command
    - @file reference completion
    - Empty / unknown input → empty results
"""

from __future__ import annotations

import pytest

# Trigger side-effect registrations so CommandFactory is populated
import ppxai.commands.handler  # noqa: F401

from ppxai.engine.completion import complete


@pytest.fixture
def populated_dir(tmp_path):
    """A tmp dir with predictable files and dirs."""
    (tmp_path / "alpha.txt").write_text("a", encoding="utf-8")
    (tmp_path / "beta.py").write_text("b", encoding="utf-8")
    sub = tmp_path / "subdir"
    sub.mkdir()
    (sub / "deep.md").write_text("d", encoding="utf-8")
    (tmp_path / ".hidden").write_text("h", encoding="utf-8")
    return tmp_path


class TestCommandCompletion:
    def test_slash_a_includes_attach(self):
        items = complete("/a")
        texts = [i["text"] for i in items]
        assert "/attach" in texts
        assert "/auto" in texts

    def test_slash_att_includes_alias(self):
        items = complete("/att")
        texts = [i["text"] for i in items]
        assert "/att" in texts
        assert "/attach" in texts

    def test_alias_has_annotation(self):
        items = complete("/att")
        att = next(i for i in items if i["text"] == "/att")
        assert "alias" in att["description"].lower()
        assert "/attach" in att["description"]
        assert att["kind"] == "alias"

    def test_slash_q_includes_quit(self):
        items = complete("/q")
        texts = [i["text"] for i in items]
        assert "/quit" in texts

    def test_slash_doctor_found(self):
        items = complete("/doc")
        texts = [i["text"] for i in items]
        assert "/doctor" in texts

    def test_empty_slash_returns_all(self):
        items = complete("/")
        # Should return all registered + aliased + builtin commands
        assert len(items) > 30

    def test_unknown_prefix_returns_empty(self):
        items = complete("/zzznonexistent")
        assert items == []

    def test_items_sorted_alphabetically(self):
        items = complete("/")
        texts = [i["text"] for i in items]
        assert texts == sorted(texts)

    def test_replace_start_covers_typed_prefix(self):
        items = complete("/att")
        for item in items:
            assert item["replace_start"] == -4  # len("/att") = 4


class TestPathCompletion:
    def test_attach_lists_dir_contents(self, populated_dir):
        items = complete("/attach ", working_dir=str(populated_dir))
        texts = [i["text"] for i in items]
        assert "alpha.txt" in texts
        assert "subdir/" in texts
        # Hidden files excluded by default
        assert ".hidden" not in texts

    def test_cd_shows_only_dirs(self, populated_dir):
        items = complete("/cd ", working_dir=str(populated_dir))
        texts = [i["text"] for i in items]
        assert "subdir/" in texts
        assert "alpha.txt" not in texts

    def test_path_prefix_filters(self, populated_dir):
        items = complete("/attach al", working_dir=str(populated_dir))
        texts = [i["text"] for i in items]
        assert texts == ["alpha.txt"]

    def test_trailing_slash_navigates(self, populated_dir):
        items = complete("/attach subdir/", working_dir=str(populated_dir))
        texts = [i["text"] for i in items]
        assert "deep.md" in texts

    def test_alias_resolves(self, populated_dir):
        # /att is alias for /attach — path completion should work
        items = complete("/att ", working_dir=str(populated_dir))
        texts = [i["text"] for i in items]
        assert "alpha.txt" in texts

    def test_hidden_files_on_dot_prefix(self, populated_dir):
        items = complete("/attach .", working_dir=str(populated_dir))
        texts = [i["text"] for i in items]
        assert ".hidden" in texts


class TestFileRefCompletion:
    def test_at_sign_triggers_file_refs(self, populated_dir):
        items = complete("look at @al", working_dir=str(populated_dir))
        texts = [i["text"] for i in items]
        assert "@alpha.txt" in texts
        assert all(i["kind"] == "file_ref" for i in items)

    def test_at_sign_fuzzy_matches(self, populated_dir):
        items = complete("@deep", working_dir=str(populated_dir))
        texts = [i["text"] for i in items]
        assert "@deep.md" in texts

    def test_at_sign_no_match(self, populated_dir):
        items = complete("@zzzznonexistent", working_dir=str(populated_dir))
        assert items == []


class TestEdgeCases:
    def test_empty_buffer(self):
        assert complete("") == []

    def test_plain_text_no_completions(self):
        assert complete("hello world") == []

    def test_cursor_mid_buffer(self):
        # Cursor at position 4 in "/att ach" → completing "/att"
        items = complete("/att ach", cursor=4)
        texts = [i["text"] for i in items]
        assert "/attach" in texts
        assert "/att" in texts


class TestContextProviderCompletion:
    def test_at_sign_surfaces_context_providers(self, populated_dir):
        items = complete("@", working_dir=str(populated_dir))
        texts = [i["text"] for i in items]
        assert "@git" in texts
        assert "@tree" in texts
        assert "@clipboard" in texts
        assert "@url" in texts

    def test_at_prefix_filters_providers(self, populated_dir):
        items = complete("@gi", working_dir=str(populated_dir))
        texts = [i["text"] for i in items]
        assert "@git" in texts
        assert "@tree" not in texts

    def test_context_providers_before_files(self, populated_dir):
        # With an empty @ query, providers should come first
        items = complete("@", working_dir=str(populated_dir))
        provider_indices = [i for i, it in enumerate(items) if it["kind"] == "context_ref"]
        file_indices = [i for i, it in enumerate(items) if it["kind"] == "file_ref"]
        if provider_indices and file_indices:
            assert max(provider_indices) < min(file_indices)

    def test_context_ref_kind(self, populated_dir):
        items = complete("@git", working_dir=str(populated_dir))
        assert any(i["kind"] == "context_ref" and i["text"] == "@git" for i in items)


class TestSubcommandCompletion:
    def test_tools_subcommands(self):
        items = complete("/tools ")
        texts = [i["text"] for i in items]
        assert "enable" in texts
        assert "disable" in texts
        assert "list" in texts

    def test_tools_prefix_filter(self):
        items = complete("/tools en")
        texts = [i["text"] for i in items]
        assert "enable" in texts
        assert "disable" not in texts

    def test_tools_help_with_tool_names(self):
        tools = [("calculator", "Evaluate math"), ("read_file", "Read file contents")]
        items = complete("/tools help ca", tool_names=tools)
        texts = [i["text"] for i in items]
        assert "calculator" in texts
        assert "read_file" not in texts

    def test_usage_subcommands(self):
        items = complete("/usage ")
        texts = [i["text"] for i in items]
        assert "show" in texts
        assert "reset" in texts

    def test_usage_show_modes(self):
        items = complete("/usage show ")
        texts = [i["text"] for i in items]
        assert "session" in texts
        assert "provider" in texts

    def test_checkpoint_subcommands(self):
        items = complete("/checkpoint ")
        texts = [i["text"] for i in items]
        assert "status" in texts
        assert "undo" in texts

    def test_checkpoint_backend_values(self):
        items = complete("/checkpoint backend ")
        texts = [i["text"] for i in items]
        assert "git" in texts
        assert "file" in texts
        assert "auto" in texts

    def test_status_subcommands(self):
        items = complete("/status ")
        texts = [i["text"] for i in items]
        assert "version" in texts
        assert "cwd" in texts

    def test_theme_lists_themes_and_subs(self):
        items = complete("/theme ")
        texts = [i["text"] for i in items]
        assert "dracula" in texts
        assert "list" in texts
        assert "emoji" in texts

    def test_theme_emoji_options(self):
        items = complete("/theme emoji ")
        texts = [i["text"] for i in items]
        assert "on" in texts
        assert "off" in texts

    def test_subcommand_replace_start(self):
        # Completing `/tools en` should replace only `en`
        items = complete("/tools en")
        for item in items:
            assert item["replace_start"] == -2

    def test_alias_resolves_for_subcommands(self):
        # Aliases should route to the canonical subcommand table.
        # `/t` is an alias for `/tools` in the default registry.
        items = complete("/t en")
        if items:
            texts = [i["text"] for i in items]
            assert "enable" in texts


class TestDynamicCompletion:
    def test_provider_without_current_provider_is_empty(self):
        items = complete("/model ")
        # No current_provider passed → empty
        assert items == []

    def test_provider_lists_all_configured(self):
        items = complete("/provider ")
        # PROVIDERS is populated by config loader; at minimum should
        # include the built-in perplexity provider once config is loaded.
        # We only assert the call shape + kind here so the test is
        # robust to config differences between dev machines.
        assert isinstance(items, list)
        for item in items:
            assert item["kind"] == "provider"


class TestTaskCompletion:
    """`/task` verb + status-aware run-id completion (v1.19.x).

    Run ids come from the `agent_runs` snapshot kwarg — only the server
    can supply it (the AgentRunRegistry is server-side state), so the
    no-snapshot case must degrade to verbs-only, never error.
    """

    _RUNS = [
        {"id": "run_aaa111", "status": "completed_pending_ack",
         "task": "summarize docs/README.md", "resumable": False},
        {"id": "run_bbb222", "status": "waiting",
         "task": "spawn a child", "resumable": False},
        {"id": "run_ccc333", "status": "interrupted",
         "task": "long research sweep", "resumable": True},
        {"id": "run_ddd444", "status": "interrupted",
         "task": "not resumable one", "resumable": False},
        {"id": "run_eee555", "status": "running",
         "task": "active run", "resumable": False},
        {"id": "run_fff666", "status": "finalized",
         "task": "already collected", "resumable": False},
    ]

    def test_task_verbs_complete(self):
        # U2 (ADR 0011): canonical verbs only — no `run` (direct launch),
        # `get`/`collect` replace `show`/`ack` in the suggestion table.
        items = complete("/task ")
        texts = [i["text"] for i in items]
        for verb in ("ls", "get", "watch", "respond",
                     "collect", "resume", "cancel", "help"):
            assert verb in texts
        assert "run" not in texts
        assert "show" not in texts
        assert "ack" not in texts

    def test_task_verb_prefix_filter(self):
        texts = [i["text"] for i in complete("/task re")]
        assert "respond" in texts
        assert "resume" in texts
        assert "collect" not in texts

    def test_collect_offers_only_held_results(self):
        items = complete("/task collect ", agent_runs=self._RUNS)
        assert [i["text"] for i in items] == ["run_aaa111"]
        assert items[0]["kind"] == "run"
        assert "completed_pending_ack" in items[0]["description"]
        assert "summarize docs/README.md" in items[0]["description"]

    def test_ack_alias_still_offers_held_results(self):
        # Muscle-memory alias: same id surface as `collect`.
        items = complete("/task ack ", agent_runs=self._RUNS)
        assert [i["text"] for i in items] == ["run_aaa111"]

    def test_respond_offers_only_waiting(self):
        items = complete("/task respond ", agent_runs=self._RUNS)
        assert [i["text"] for i in items] == ["run_bbb222"]

    def test_respond_second_arg_offers_answers(self):
        texts = [i["text"] for i in
                 complete("/task respond run_bbb222 ", agent_runs=self._RUNS)]
        assert texts == ["approve", "deny"]

    def test_resume_requires_resumable(self):
        items = complete("/task resume ", agent_runs=self._RUNS)
        assert [i["text"] for i in items] == ["run_ccc333"]

    def test_cancel_offers_in_flight_only(self):
        texts = [i["text"] for i in
                 complete("/task cancel ", agent_runs=self._RUNS)]
        assert set(texts) == {"run_bbb222", "run_eee555"}

    def test_get_offers_everything(self):
        texts = [i["text"] for i in
                 complete("/task get ", agent_runs=self._RUNS)]
        assert len(texts) == len(self._RUNS)

    def test_show_alias_offers_everything(self):
        texts = [i["text"] for i in
                 complete("/task show ", agent_runs=self._RUNS)]
        assert len(texts) == len(self._RUNS)

    def test_id_prefix_filter_and_replace_start(self):
        items = complete("/task get run_a", agent_runs=self._RUNS)
        assert [i["text"] for i in items] == ["run_aaa111"]
        assert items[0]["replace_start"] == -len("run_a")

    def test_no_snapshot_degrades_to_empty_ids(self):
        assert complete("/task collect ") == []

    def test_launch_prompt_gets_no_id_completion(self):
        # U2: a non-verb first token is a direct-launch prompt, not an id slot.
        assert complete("/task summarize ", agent_runs=self._RUNS) == []


class TestTaskCompletionRoute:
    """POST /complete supplies the agent-run snapshot (server-side glue).

    The registry is server state, so the route — not the engine — is where
    run ids enter the completion pipeline. Pin that wiring: a held run must
    surface for `/task ack `, and a non-/task buffer must not touch the
    registry snapshot path at all.
    """

    def _client(self, tmp_path, monkeypatch):
        from types import SimpleNamespace
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        import ppxai.server.state as state
        from ppxai.engine.agent_runs import (
            AgentRunRegistry, FilesystemAgentRunStore, RunMeta,
        )
        from ppxai.server.routes import completion as completion_route

        reg = AgentRunRegistry(FilesystemAgentRunStore(tmp_path / "runs"))
        reg._store.persist_meta(RunMeta(
            run_id="run_held1", task="summarize docs", tools=["read_file"],
            status="completed_pending_ack", created_at=1.0,
        ))
        monkeypatch.setattr(state, "_agent_run_registry", reg)

        app = FastAPI()
        app.include_router(completion_route.router)
        # The route only needs `.engine` off the session; None short-circuits
        # the engine-derived kwargs (working dir / provider / tools).
        app.dependency_overrides[completion_route.get_session] = (
            lambda: SimpleNamespace(engine=None)
        )
        return TestClient(app)

    def test_task_ack_offers_held_run(self, tmp_path, monkeypatch):
        client = self._client(tmp_path, monkeypatch)
        r = client.post("/complete", json={"buffer": "/task collect "})
        assert r.status_code == 200
        items = r.json()["items"]
        assert [i["text"] for i in items] == ["run_held1"]
        assert items[0]["kind"] == "run"

    def test_non_task_buffer_gets_no_run_items(self, tmp_path, monkeypatch):
        client = self._client(tmp_path, monkeypatch)
        r = client.post("/complete", json={"buffer": "/usage "})
        assert r.status_code == 200
        assert all(i["kind"] != "run" for i in r.json()["items"])


class TestClientGating:
    """Client-side commands are surfaced only to clients that implement
    them (Item 40 follow-up, 2026-07-12).

    /agentrun + /agentruns are web-only; /task + /token are web+VSCode;
    the in-process TUIs (rich/textual) implement none of them. Before
    gating, autocomplete taught TUI/VSCode users to type commands that
    answered "Unknown command".
    """

    _GATED_WEB_ONLY = {"/agentrun", "/agentruns"}
    _GATED_WEB_VSCODE = {"/task", "/token"}

    def _names(self, prefix, client):
        return {i["text"] for i in complete(prefix, client=client)}

    def test_web_sees_all_client_side_commands(self):
        names = self._names("/", "web")
        assert self._GATED_WEB_ONLY <= names
        assert self._GATED_WEB_VSCODE <= names

    def test_vscode_sees_task_and_token_but_not_agentrun(self):
        names = self._names("/", "vscode")
        assert self._GATED_WEB_VSCODE <= names
        assert not (self._GATED_WEB_ONLY & names)

    def test_tuis_see_no_client_side_commands(self):
        for client in ("rich", "textual"):
            names = self._names("/", client)
            assert not ((self._GATED_WEB_ONLY | self._GATED_WEB_VSCODE)
                        & names), client
            # Universal builtins + factory commands stay visible.
            assert "/quit" in names

    def test_none_client_fails_open(self):
        # Legacy callers (no client declared) keep the full catalog.
        names = self._names("/", None)
        assert self._GATED_WEB_ONLY <= names
        assert self._GATED_WEB_VSCODE <= names

    def test_unknown_client_gets_only_universal(self):
        names = self._names("/", "some-future-client")
        assert not ((self._GATED_WEB_ONLY | self._GATED_WEB_VSCODE)
                    & names)

    def test_clients_tag_never_leaks_into_items(self):
        # The internal `clients` set is not part of the JSON item schema
        # (FastAPI could not serialize it).
        for item in complete("/", client="web"):
            assert "clients" not in item

    def test_arg_completion_gated_too(self):
        # /token subcommands only where /token exists…
        assert [i["text"] for i in complete("/token ", client="web")] == \
            ["status", "set", "mint", "clear"]
        assert complete("/token ", client="rich") == []
        # …same for /task verbs.
        assert complete("/task ", client="textual") == []
        assert any(i["text"] == "get"
                   for i in complete("/task ", client="vscode"))

    def test_route_passes_client_through(self, tmp_path, monkeypatch):
        route = TestTaskCompletionRoute()
        client = route._client(tmp_path, monkeypatch)
        # VSCode sees /token (and the response serializes cleanly).
        r = client.post("/complete",
                        json={"buffer": "/to", "client": "vscode"})
        assert r.status_code == 200
        assert "/token" in [i["text"] for i in r.json()["items"]]
        # A TUI-declared caller gets no run-id items even with a held run.
        r = client.post("/complete",
                        json={"buffer": "/task collect ", "client": "rich"})
        assert r.status_code == 200
        assert r.json()["items"] == []
