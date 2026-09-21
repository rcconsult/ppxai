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

import re
from pathlib import Path

import pytest
from prompt_toolkit.document import Document

# Trigger side-effect registrations so CommandFactory is populated
import ppxai.commands.handler  # noqa: F401
from ppxai.commands.factory import CommandFactory
from ppxai.engine.completion import complete as engine_complete
from ppxai.rich.main import PPXAICompleter
from ppxai.tui.completer import TextualCompleter

REPO_ROOT = Path(__file__).resolve().parents[1]


def roster_for(client=None):
    """The roster as `complete()` now takes it (ADR 0007 step 4).

    A test may import `ppxai.commands`; `ppxai/engine/completion.py` may
    not — that edge is what step 4 removed, and
    `tests/test_no_new_lazy_imports.py::TestEngineImportsNoCommands`
    holds it at zero. The caller reads the registry and hands over plain
    data, already filtered for its client.
    """
    return CommandFactory.roster(client)["commands"]


def complete(buffer, cursor=-1, *, client=None, **kwargs):
    """Test-side stand-in for the three real callers.

    They each fetch `CommandFactory.roster(<their client>)["commands"]`
    and pass it in; this helper does the same from a `client=` kwarg, so
    every assertion below reads exactly as it did before step 4 and the
    behaviour comparison is honest rather than rewritten.
    """
    return engine_complete(buffer, cursor, roster=roster_for(client), **kwargs)


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


class TestRunCompletion:
    """U3 (ADR 0011): the /run family shares the /task completion machinery
    with its own verb table and oneshot-kind id filtering."""

    _RUNS = [
        {"id": "run_task0000001", "status": "completed_pending_ack",
         "task": "a task-tier run", "kind": "task", "resumable": False},
        {"id": "run_one00000001", "status": "completed_pending_ack",
         "task": "a one-off run", "kind": "oneshot", "resumable": False},
    ]

    def test_run_verbs_complete(self):
        texts = [i["text"] for i in complete("/run ")]
        for verb in ("ls", "get", "watch", "collect", "cancel", "help"):
            assert verb in texts
        # respond/resume exist but are noise for oneshots — not offered.
        assert "respond" not in texts
        assert "resume" not in texts

    def test_run_ids_filtered_to_oneshot_kind(self):
        items = complete("/run collect ", agent_runs=self._RUNS)
        assert [i["text"] for i in items] == ["run_one00000001"]

    def test_task_ids_filtered_to_task_kind(self):
        items = complete("/task collect ", agent_runs=self._RUNS)
        assert [i["text"] for i in items] == ["run_task0000001"]

    def test_legacy_snapshot_without_kind_reads_as_task(self):
        runs = [{"id": "run_legacy00001", "status": "completed_pending_ack",
                 "task": "pre-U3 run", "resumable": False}]
        assert complete("/run collect ", agent_runs=runs) == []
        assert [i["text"] for i in complete("/task collect ", agent_runs=runs)] \
            == ["run_legacy00001"]


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
            AgentRunRegistry,
            FilesystemAgentRunStore,
            RunMeta,
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

    U3 (ADR 0011): /agentrun + /agentruns are RETIRED (hard removal).

    **Updated for T8b (v1.19.1).** /task and /run were gated to web+VSCode
    while the TUIs had no channel to the run registry. The embed decision
    removed that: both are now real `CommandFactory` commands and are
    UNIVERSAL. Availability is decided per verb by a capability (a live event
    loop, needed only by launch/resume) rather than per client by a name — so
    a TUI user who completes `/task` gets working `ls`/`get`/`cancel`, and a
    precise message for the verbs their client cannot drive yet.

    /token remains genuinely client-side (web command-dispatcher.js +
    VSCode chatPanel.ts), so it stays gated — which is what keeps these
    tests meaningful rather than vacuous.
    """

    _RETIRED = {"/agentrun", "/agentruns"}
    _GATED_WEB_VSCODE = {"/token"}
    _NOW_UNIVERSAL = {"/task", "/run"}

    def _names(self, prefix, client):
        return {i["text"] for i in complete(prefix, client=client)}

    def test_web_sees_all_client_side_commands(self):
        names = self._names("/", "web")
        assert self._GATED_WEB_VSCODE <= names
        assert not (self._RETIRED & names)

    def test_vscode_sees_the_same_client_side_commands(self):
        names = self._names("/", "vscode")
        assert self._GATED_WEB_VSCODE <= names
        assert not (self._RETIRED & names)

    def test_tuis_see_no_client_side_commands(self):
        for client in ("rich", "textual"):
            names = self._names("/", client)
            assert not (self._GATED_WEB_VSCODE & names), client
            # /quit is gated to {rich, textual} (owner decision,
            # 2026-09-20) — factory commands stay visible here too.
            assert "/quit" in names

    def test_tuis_now_see_task_and_run(self):
        """T8b inverted the old assertion — deliberately, not by accident.

        These were gated away from the TUIs precisely because they could not
        work there. They can now (partially, per verb), so hiding them would
        teach the opposite wrong lesson from the one the gating fixed.
        """
        for client in ("rich", "textual"):
            assert self._NOW_UNIVERSAL <= self._names("/", client), client

    def test_task_and_run_are_listed_once(self):
        """They are factory commands now; a leftover client-side entry would
        double-list them in every client's completions."""
        for client in ("web", "vscode", "rich", "textual", None):
            items = [i for i in complete("/", client=client)
                     if i["text"] in self._NOW_UNIVERSAL]
            texts = [i["text"] for i in items]
            assert len(texts) == len(set(texts)), (client, texts)

    def test_none_client_fails_open(self):
        # Legacy callers (no client declared) keep the full catalog —
        # which after U3 no longer contains the retired names either.
        names = self._names("/", None)
        assert self._GATED_WEB_VSCODE <= names
        assert not (self._RETIRED & names)

    def test_unknown_client_gets_only_universal(self):
        names = self._names("/", "some-future-client")
        assert not (self._GATED_WEB_VSCODE & names)

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
        # …but /task verbs are NOT gated any more (T8b): the TUIs run these.
        # `get` must be offered everywhere, since it works everywhere.
        for client in ("textual", "rich", "vscode", "web"):
            assert any(i["text"] == "get"
                       for i in complete("/task ", client=client)), client

    def test_route_passes_client_through(self, tmp_path, monkeypatch):
        route = TestTaskCompletionRoute()
        client = route._client(tmp_path, monkeypatch)
        # VSCode sees /token (and the response serializes cleanly).
        r = client.post("/complete",
                        json={"buffer": "/to", "client": "vscode"})
        assert r.status_code == 200
        assert "/token" in [i["text"] for i in r.json()["items"]]
        # T8b: a TUI-declared caller DOES get run-id items now — collecting a
        # held result is a synchronous registry op that works in every client,
        # so completing the id it needs must work there too. Previously this
        # asserted [] because /task did not exist in the TUIs at all.
        r = client.post("/complete",
                        json={"buffer": "/task collect ", "client": "rich"})
        assert r.status_code == 200
        assert "run_held1" in [i["text"] for i in r.json()["items"]]


# =============================================================================
# ADR 0007 step 4 — completion is DERIVED from the command spec
# =============================================================================
#
# Before step 4 this module held seven hand-written `_*_SUBCOMMANDS` tables
# and reached UP into `ppxai.commands` to read the roster. Both are gone: the
# caller passes the roster in as plain data, and every first-level subcommand
# comes off `CommandSpec.subcommands`. These tests pin that the derivation is
# real — they compare against the SPEC, never against a copied list, so a
# table quietly reappearing anywhere fails them.

COMPLETION_SOURCE = (
    REPO_ROOT / "ppxai" / "engine" / "completion.py"
).read_text(encoding="utf-8")


class TestNoHandWrittenSubcommandTables:
    """The deletion the plan tracks: no `_*_SUBCOMMANDS` table survives."""

    def test_the_source_is_where_we_think(self):
        assert "def complete(" in COMPLETION_SOURCE

    def test_the_detector_would_see_a_table(self):
        # Guard first: the regex must match the exact shape that was deleted.
        assert re.search(
            r"_[A-Z_]+_SUBCOMMANDS\s*:",
            '_TOOLS_SUBCOMMANDS: list[tuple[str, str]] = [\n]',
        )

    def test_no_subcommand_table_remains(self):
        offenders = re.findall(r"^_[A-Z_]+_SUBCOMMANDS\s*[:=]",
                               COMPLETION_SOURCE, re.M)
        assert offenders == [], (
            "a hand-written subcommand table is back in "
            "ppxai/engine/completion.py. Declare it on the command's "
            "CommandSpec(subcommands=[...]) instead — completion reads the "
            f"roster the caller hands in (ADR 0007 step 4): {offenders}"
        )


class TestSubcommandsComeFromTheSpec:
    """Every migrated command's first-level completion IS its declaration.

    Compared against `CommandSpec.subcommands` rather than a hand-copied
    list: if the two were restated, this test would pass while they drifted
    — which is the failure mode the whole record exists to remove.
    """

    MIGRATED = ["tools", "usage", "checkpoint", "status", "theme",
                "task", "run", "token"]

    @pytest.mark.parametrize("name", MIGRATED)
    def test_offered_equals_declared(self, name):
        spec = CommandFactory.get(name)
        assert spec is not None and spec.subcommands, name
        declared = [sub for sub, _ in spec.subcommands]
        client = "web" if name == "token" else "rich"
        offered = [i["text"] for i in complete(f"/{name} ", client=client)
                   if i["kind"] == "subcommand"]
        assert offered == declared, name

    @pytest.mark.parametrize("name", MIGRATED)
    def test_descriptions_come_from_the_spec_too(self, name):
        spec = CommandFactory.get(name)
        declared = dict(spec.subcommands)
        client = "web" if name == "token" else "rich"
        for item in complete(f"/{name} ", client=client):
            if item["kind"] == "subcommand":
                assert item["description"] == declared[item["text"]], name

    def test_a_declared_subcommand_flows_through_to_completion(self):
        """Liveness: add one to the DATA and completion must offer it."""
        roster = [dict(e) for e in roster_for("rich")]
        entry = next(e for e in roster if e["name"] == "status")
        entry["subcommands"] = entry["subcommands"] + [
            {"name": "zebra", "description": "probe", "sensitive": False}
        ]
        offered = [i["text"] for i in engine_complete("/status ", roster=roster)]
        assert offered[-1] == "zebra"

    def test_prefix_filtering_still_narrows(self):
        assert [i["text"] for i in complete("/checkpoint ba", client="rich")] \
            == ["backend"]

    def test_second_level_arguments_are_unaffected(self):
        """The nested tables stayed in completion (the flat schema cannot
        hold them) and must keep working."""
        assert [i["text"] for i in complete("/checkpoint backend ", client="rich")] \
            == ["git", "file", "auto", "none"]
        assert [i["text"] for i in complete("/usage show ", client="rich")] \
            == ["session", "provider", "model", "off"]
        assert [i["text"] for i in complete("/theme emoji ", client="rich")] \
            == ["on", "off"]

    def test_no_duplicate_subcommand_within_a_command(self):
        """Subcommand names are not aliases, so nothing else pins this —
        but a duplicate would offer the same completion twice."""
        for name, spec in CommandFactory._registry.items():
            declared = [sub for sub, _ in spec.subcommands]
            assert len(declared) == len(set(declared)), name


class TestAbsentRosterOffersNoCommands:
    """No fallback: with no roster, completion does not reach for the
    registry — it simply offers no slash commands. Paths and @refs, which
    need no roster at all, must keep working."""

    @pytest.mark.parametrize("roster", [None, []])
    def test_no_command_names(self, roster):
        assert engine_complete("/to", roster=roster) == []
        assert engine_complete("/", roster=roster) == []

    @pytest.mark.parametrize("roster", [None, []])
    def test_no_subcommands(self, roster):
        assert engine_complete("/tools ", roster=roster) == []
        assert engine_complete("/token set", roster=roster) == []

    @pytest.mark.parametrize("roster", [None, []])
    def test_path_completion_still_works(self, roster, populated_dir):
        items = engine_complete("/attach ", roster=roster,
                                working_dir=str(populated_dir))
        assert "alpha.txt" in [i["text"] for i in items]

    @pytest.mark.parametrize("roster", [None, []])
    def test_at_file_completion_still_works(self, roster, populated_dir):
        items = engine_complete("look at @al", roster=roster,
                                working_dir=str(populated_dir))
        assert "@alpha.txt" in [i["text"] for i in items]

    def test_the_roster_argument_is_required(self):
        """A forgotten roster is a TypeError at the call site, not a
        silently empty dropdown."""
        with pytest.raises(TypeError):
            engine_complete("/to")


class TestTheThreeCallersPassTheirClientId:
    """Each caller reads the roster for ITS client and hands it over.

    Source-text, because the behavioural half lives in
    `tests/test_completer_dynamic.py` (Rich, driven end to end) and in the
    route tests above (server). What a source check adds is the client ID:
    a caller that fetched `roster()` unfiltered would still complete, just
    with commands its user cannot run.
    """

    CALLERS = {
        "ppxai/rich/main.py": '"rich"',
        "ppxai/tui/completer.py": '"textual"',
        "ppxai/server/routes/completion.py": "request.client",
    }

    @pytest.mark.parametrize("path,client", sorted(CALLERS.items()))
    def test_caller_passes_a_roster_for_its_client(self, path, client):
        src = (REPO_ROOT / path).read_text(encoding="utf-8")
        assert f'roster=CommandFactory.roster({client})["commands"]' in src, path

    @pytest.mark.parametrize("path", sorted(CALLERS))
    def test_caller_passes_no_client_kwarg(self, path):
        """`complete()` has no `client` parameter any more — the gate is
        the roster. A leftover `client=` would be a TypeError, but the
        source check names the file."""
        src = (REPO_ROOT / path).read_text(encoding="utf-8")
        assert "client=client" not in src, path

    def test_rich_completes_through_the_real_adapter(self):
        """Behavioural end of the same claim: /token is web+vscode-only,
        so Rich's own completer must not offer it — and it can only know
        that from the roster it fetched for "rich"."""


        doc = Document(text="/to", cursor_position=3)
        texts = [c.text for c in
                 PPXAICompleter().get_completions(doc, complete_event=None)]
        assert "/tools" in texts
        assert "/token" not in texts

    def test_textual_completes_through_the_real_adapter(self, tmp_path):

        completer = TextualCompleter(working_dir=tmp_path)
        texts = [r for r, _ in completer.get_completions("/to")]
        assert any(t.startswith("/tools") for t in texts)
        assert not any(t.startswith("/token") for t in texts)
