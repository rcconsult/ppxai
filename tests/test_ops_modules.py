"""Tests for extracted ops modules: bootstrap_ops, checkpoint_ops, consent_ops, session_ops."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ppxai.constants import ConsentMode, ConsentResponse, ShellRiskLevel
from ppxai.engine.bootstrap_ops import (
    get_active_hints,
    get_bootstrap_prompt,
    get_bootstrap_status,
    load_bootstrap_context,
)
from ppxai.engine.checkpoint_ops import (
    clear_file_checkpoints,
    commit_agent_changes,
    create_checkpoint,
    get_checkpoint_status,
    list_checkpoints,
    set_checkpoint_backend,
    undo_last_checkpoint,
)
from ppxai.engine.consent_ops import (
    classify_command,
    request_file_edit_consent,
    request_shell_consent,
)
from ppxai.engine.session_ops import (
    clear_injected_contexts,
    export_answer,
    export_conversation,
    get_context_info,
    get_history,
    get_status,
    get_usage,
    restore_session,
)
from ppxai.engine.types import EventType, Message

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_engine(**overrides):
    """Create a mock engine with common attributes."""
    engine = MagicMock()
    engine._bootstrap_context = None
    engine._bootstrap_sources = []
    engine._checkpoint_manager = None
    engine._agent_mode = False
    engine._last_checkpoint_id = None
    engine._event_queue = []
    engine._event_queue_lock = __import__('threading').Lock()
    engine.enqueue_event = lambda evt: engine._event_queue.append(evt)
    engine._shell_config = {}
    engine._injected_contexts = []
    engine.provider_name = "openai"
    engine.model = "gpt-4"
    engine.tools_enabled = False
    engine.auto_inject_context = False
    engine.provider = MagicMock()
    engine.consent_callback = None
    engine.shell_consent_callback = None
    engine.session = MagicMock()
    engine.session.messages = []
    engine.session.edit_consent_mode = ConsentMode.PROMPT
    engine.session.shell_consent_mode = ConsentMode.PROMPT
    engine.session.allowed_files = set()
    engine.session.allowed_commands = set()
    engine.session.tools_enabled = False
    engine.context_injector = MagicMock()
    engine.tool_manager = MagicMock()
    engine.state = MagicMock()
    for k, v in overrides.items():
        setattr(engine, k, v)
    return engine


def _make_bootstrap_context(**overrides):
    """Create a mock bootstrap context."""
    ctx = MagicMock()
    ctx.char_count = overrides.get("char_count", 500)
    ctx.has_hints = overrides.get("has_hints", True)
    ctx.provider_hints = overrides.get("provider_hints", {"openai": "hint1"})
    ctx.model_hints = overrides.get("model_hints", {"gpt-4*": "hint2"})
    ctx.source_file = overrides.get("source_file", "AGENTS.md")
    return ctx


def _make_source(path="/project/AGENTS.md", scope="project", size=500):
    """Create a mock bootstrap source."""
    src = MagicMock()
    src.path = Path(path)
    src.scope = scope
    src.size = size
    return src


# ===========================================================================
# TestBootstrapOps
# ===========================================================================

class TestBootstrapOps:
    """Tests for ppxai.engine.bootstrap_ops."""

    def test_load_bootstrap_context_found(self):
        engine = _make_engine()
        ctx = _make_bootstrap_context()
        sources = [_make_source()]
        engine.context_injector.load_bootstrap_context_merged.return_value = (ctx, sources)

        result = load_bootstrap_context(engine)

        assert result is True
        assert engine._bootstrap_context is ctx
        assert engine._bootstrap_sources is sources

    def test_load_bootstrap_context_not_found(self):
        engine = _make_engine()
        engine.context_injector.load_bootstrap_context_merged.return_value = (None, [])

        result = load_bootstrap_context(engine)

        assert result is False
        assert engine._bootstrap_context is None
        assert engine._bootstrap_sources == []

    def test_get_bootstrap_status_not_loaded(self):
        engine = _make_engine()

        status = get_bootstrap_status(engine)

        assert status["loaded"] is False
        assert status["sources"] == []
        assert status["char_count"] == 0
        assert status["has_hints"] is False
        assert status["total_size"] == 0

    def test_get_bootstrap_status_loaded(self):
        ctx = _make_bootstrap_context(char_count=1200)
        src1 = _make_source(path="/global/AGENTS.md", scope="global", size=400)
        src2 = _make_source(path="/project/AGENTS.md", scope="project", size=800)
        engine = _make_engine(
            _bootstrap_context=ctx,
            _bootstrap_sources=[src1, src2],
        )

        status = get_bootstrap_status(engine)

        assert status["loaded"] is True
        assert len(status["sources"]) == 2
        assert status["sources"][0]["scope"] == "global"
        assert status["sources"][1]["scope"] == "project"
        assert status["total_size"] == 1200
        assert status["char_count"] == 1200
        assert status["has_hints"] is True
        assert "openai" in status["provider_hints"]
        assert "gpt-4*" in status["model_hints"]
        assert len(status["source_paths"]) == 2

    def test_get_bootstrap_prompt_not_loaded(self):
        engine = _make_engine()
        assert get_bootstrap_prompt(engine) == ""

    def test_get_bootstrap_prompt_loaded(self):
        ctx = _make_bootstrap_context()
        ctx.get_prompt_for.return_value = "You are helpful."
        engine = _make_engine(_bootstrap_context=ctx)

        result = get_bootstrap_prompt(engine)

        assert result == "You are helpful."
        ctx.get_prompt_for.assert_called_once_with("openai", "gpt-4")

    def test_get_active_hints_not_loaded(self):
        engine = _make_engine()

        hints = get_active_hints(engine)

        assert hints["loaded"] is False
        assert hints["provider"] == "openai"
        assert hints["model"] == "gpt-4"
        assert hints["provider_hints"] == []
        assert hints["model_hints"] == []

    def test_get_active_hints_loaded(self):
        ctx = _make_bootstrap_context()
        ctx.get_active_hints_for.return_value = {
            "provider_hints": ["hint1"],
            "model_hints": ["hint2"],
            "inherited_local": False,
            "matched_patterns": ["gpt-4*"],
        }
        src = _make_source()
        engine = _make_engine(
            _bootstrap_context=ctx,
            _bootstrap_sources=[src],
        )

        hints = get_active_hints(engine)

        assert hints["loaded"] is True
        assert hints["provider_hints"] == ["hint1"]
        assert hints["model_hints"] == ["hint2"]
        assert hints["matched_patterns"] == ["gpt-4*"]
        assert hints["source"] == "AGENTS.md"
        assert len(hints["sources"]) == 1
        ctx.get_active_hints_for.assert_called_once_with("openai", "gpt-4")


# ===========================================================================
# TestCheckpointOps
# ===========================================================================

class TestCheckpointOps:
    """Tests for ppxai.engine.checkpoint_ops."""

    def test_create_checkpoint_disabled(self):
        engine = _make_engine()
        assert create_checkpoint(engine, "test") is None

    def test_create_checkpoint_no_agent_mode(self):
        engine = _make_engine(_checkpoint_manager=MagicMock())
        assert create_checkpoint(engine, "test") is None

    def test_create_checkpoint_success_git(self):
        mgr = MagicMock()
        mgr.create_checkpoint.return_value = "abc12345"
        mgr.get_backend_name.return_value = "git"
        engine = _make_engine(
            _checkpoint_manager=mgr,
            _agent_mode=True,
        )

        result = create_checkpoint(engine, "task desc")

        assert result == "abc12345"
        assert engine._last_checkpoint_id == "abc12345"
        assert len(engine._event_queue) == 1
        evt = engine._event_queue[0]
        assert evt.type == EventType.STATUS
        assert "abc12345" in evt.data

    def test_create_checkpoint_success_file(self):
        mgr = MagicMock()
        mgr.create_checkpoint.return_value = "snap_001"
        mgr.get_backend_name.return_value = "file"
        engine = _make_engine(
            _checkpoint_manager=mgr,
            _agent_mode=True,
        )

        result = create_checkpoint(engine, "task")
        assert result == "snap_001"
        assert "Snapshot" in engine._event_queue[0].data

    def test_create_checkpoint_manager_returns_none(self):
        mgr = MagicMock()
        mgr.create_checkpoint.return_value = None
        engine = _make_engine(
            _checkpoint_manager=mgr,
            _agent_mode=True,
        )

        assert create_checkpoint(engine, "test") is None
        assert engine._last_checkpoint_id is None

    def test_undo_last_checkpoint_no_manager(self):
        engine = _make_engine()
        assert undo_last_checkpoint(engine) is False

    def test_undo_last_checkpoint_no_id(self):
        engine = _make_engine(_checkpoint_manager=MagicMock())
        assert undo_last_checkpoint(engine) is False

    def test_undo_last_checkpoint_success(self):
        mgr = MagicMock()
        mgr.restore_checkpoint.return_value = True
        mgr.get_backend_name.return_value = "git"
        engine = _make_engine(
            _checkpoint_manager=mgr,
            _last_checkpoint_id="abc12345",
        )

        result = undo_last_checkpoint(engine)

        assert result is True
        assert engine._last_checkpoint_id is None
        assert len(engine._event_queue) == 1
        assert "reverted" in engine._event_queue[0].data

    def test_undo_last_checkpoint_file_backend(self):
        mgr = MagicMock()
        mgr.restore_checkpoint.return_value = True
        mgr.get_backend_name.return_value = "file"
        engine = _make_engine(
            _checkpoint_manager=mgr,
            _last_checkpoint_id="snap_001",
        )

        result = undo_last_checkpoint(engine)
        assert result is True
        assert "restored" in engine._event_queue[0].data

    def test_undo_last_checkpoint_restore_fails(self):
        mgr = MagicMock()
        mgr.restore_checkpoint.return_value = False
        engine = _make_engine(
            _checkpoint_manager=mgr,
            _last_checkpoint_id="abc12345",
        )

        assert undo_last_checkpoint(engine) is False

    def test_commit_agent_changes_disabled(self):
        engine = _make_engine()
        assert commit_agent_changes(engine, "changes") is None

    def test_commit_agent_changes_not_git(self):
        mgr = MagicMock()
        mgr.get_backend_name.return_value = "file"
        engine = _make_engine(
            _checkpoint_manager=mgr,
            _agent_mode=True,
        )
        assert commit_agent_changes(engine, "changes") is None

    @patch("ppxai.engine.checkpoint_ops.subprocess")
    def test_commit_agent_changes_no_changes(self, mock_subprocess):
        mgr = MagicMock()
        mgr.get_backend_name.return_value = "git"
        engine = _make_engine(
            _checkpoint_manager=mgr,
            _agent_mode=True,
        )
        engine.context_injector.working_dir = "/project"

        # git status --porcelain returns empty
        mock_subprocess.run.return_value = MagicMock(stdout="")
        assert commit_agent_changes(engine, "changes") is None

    @patch("ppxai.engine.checkpoint_ops.subprocess")
    def test_commit_agent_changes_success(self, mock_subprocess):
        mgr = MagicMock()
        mgr.get_backend_name.return_value = "git"
        engine = _make_engine(
            _checkpoint_manager=mgr,
            _agent_mode=True,
        )
        engine.context_injector.working_dir = "/project"

        # git status returns changes, then git add, git commit, git rev-parse
        status_result = MagicMock(stdout="M file.py\n")
        rev_parse_result = MagicMock(stdout="deadbeef1234\n")
        mock_subprocess.run.side_effect = [
            status_result,   # git status
            MagicMock(),      # git add
            MagicMock(),      # git commit
            rev_parse_result  # git rev-parse HEAD
        ]

        result = commit_agent_changes(engine, "fix bug")
        assert result == "deadbeef1234"
        assert engine._last_checkpoint_id == "deadbeef1234"

    def test_get_checkpoint_status_disabled(self):
        engine = _make_engine()
        status = get_checkpoint_status(engine)

        assert status["enabled"] is False
        assert status["backend"] == "none"
        assert status["is_valid"] is False

    def test_get_checkpoint_status_enabled_no_checkpoint(self):
        mgr = MagicMock()
        mgr.is_enabled.return_value = True
        mgr.get_backend_name.return_value = "git"
        mgr.get_status_description.return_value = "Git backend ready"
        engine = _make_engine(_checkpoint_manager=mgr)

        status = get_checkpoint_status(engine)

        assert status["enabled"] is True
        assert status["backend"] == "git"
        assert status["last_checkpoint"] is None
        assert status["is_valid"] is False

    def test_get_checkpoint_status_valid_checkpoint(self):
        mgr = MagicMock()
        mgr.is_enabled.return_value = True
        mgr.get_backend_name.return_value = "git"
        mgr.is_checkpoint_valid.return_value = (True, "Checkpoint is valid")
        mgr.get_status_description.return_value = "Ready"
        engine = _make_engine(
            _checkpoint_manager=mgr,
            _last_checkpoint_id="abc123",
        )

        status = get_checkpoint_status(engine)

        assert status["is_valid"] is True
        assert status["last_checkpoint"] == "abc123"

    def test_get_checkpoint_status_invalid_clears_id(self):
        mgr = MagicMock()
        mgr.is_enabled.return_value = True
        mgr.get_backend_name.return_value = "git"
        mgr.is_checkpoint_valid.return_value = (False, "Checkpoint expired")
        mgr.get_status_description.return_value = "Ready"
        engine = _make_engine(
            _checkpoint_manager=mgr,
            _last_checkpoint_id="old123",
        )

        status = get_checkpoint_status(engine)

        assert status["is_valid"] is False
        assert engine._last_checkpoint_id is None

    def test_list_checkpoints_disabled(self):
        engine = _make_engine()
        assert list_checkpoints(engine) == []

    def test_list_checkpoints_returns_limited(self):
        mgr = MagicMock()
        mgr.list_checkpoints.return_value = [
            ("id1", "desc1", "2026-01-01"),
            ("id2", "desc2", "2026-01-02"),
            ("id3", "desc3", "2026-01-03"),
        ]
        engine = _make_engine(_checkpoint_manager=mgr)

        result = list_checkpoints(engine, limit=2)

        assert len(result) == 2
        assert result[0] == {"id": "id1", "description": "desc1", "timestamp": "2026-01-01"}
        assert result[1] == {"id": "id2", "description": "desc2", "timestamp": "2026-01-02"}

    @patch("ppxai.engine.checkpoint_ops.CheckpointManager")
    def test_set_checkpoint_backend_valid(self, mock_cls):
        engine = _make_engine()
        engine.session.session_name = "sess1"

        result = set_checkpoint_backend(engine, "file")

        assert result is True
        mock_cls.assert_called_once()
        assert engine._checkpoint_manager is mock_cls.return_value

    def test_set_checkpoint_backend_invalid(self):
        engine = _make_engine()
        assert set_checkpoint_backend(engine, "invalid") is False

    def test_clear_file_checkpoints_disabled(self):
        engine = _make_engine()
        assert clear_file_checkpoints(engine) == 0

    def test_clear_file_checkpoints_not_file_backend(self):
        mgr = MagicMock()
        mgr.backend = MagicMock()  # not a FileCheckpointBackend
        engine = _make_engine(_checkpoint_manager=mgr)
        # isinstance check will fail because backend is a MagicMock, not FileCheckpointBackend
        assert clear_file_checkpoints(engine) == 0

    def test_clear_file_checkpoints_success(self):
        from ppxai.checkpoint import FileCheckpointBackend as RealFCB

        real_backend = MagicMock(spec=RealFCB)
        real_backend.cleanup_old_checkpoints = MagicMock()
        mgr = MagicMock()
        mgr.backend = real_backend
        mgr.list_checkpoints.side_effect = [
            [("a",), ("b",), ("c",)],  # before cleanup
            [("c",)],                    # after cleanup
        ]
        engine = _make_engine(_checkpoint_manager=mgr)

        result = clear_file_checkpoints(engine)
        assert result == 2
        real_backend.cleanup_old_checkpoints.assert_called_once_with(keep_last=0)


# ===========================================================================
# TestConsentOps
# ===========================================================================

class TestConsentOps:
    """Tests for ppxai.engine.consent_ops."""

    @pytest.mark.asyncio
    async def test_file_consent_always_mode(self):
        engine = _make_engine()
        engine.session.edit_consent_mode = ConsentMode.ALWAYS

        result = await request_file_edit_consent(engine, "/tmp/test.py")
        assert result is True

    @pytest.mark.asyncio
    async def test_file_consent_never_mode(self):
        engine = _make_engine()
        engine.session.edit_consent_mode = ConsentMode.NEVER

        result = await request_file_edit_consent(engine, "/tmp/test.py")
        assert result is False

    @pytest.mark.asyncio
    async def test_file_consent_already_allowed(self):
        path = Path("/tmp/test.py").resolve()
        engine = _make_engine()
        engine.session.allowed_files = {path}

        result = await request_file_edit_consent(engine, "/tmp/test.py")
        assert result is True

    @pytest.mark.asyncio
    async def test_file_consent_no_callback_allows(self):
        engine = _make_engine()
        engine.consent_callback = None

        result = await request_file_edit_consent(engine, "/tmp/test.py")
        assert result is True

    @pytest.mark.asyncio
    async def test_file_consent_callback_yes(self):
        engine = _make_engine()
        engine.consent_callback = AsyncMock(return_value=(True, ConsentResponse.YES))

        result = await request_file_edit_consent(engine, "/tmp/test.py")
        assert result is True
        resolved = Path("/tmp/test.py").resolve()
        assert resolved in engine.session.allowed_files

    @pytest.mark.asyncio
    async def test_file_consent_callback_always(self):
        engine = _make_engine()
        engine.consent_callback = AsyncMock(return_value=(True, ConsentResponse.ALWAYS))

        result = await request_file_edit_consent(engine, "/tmp/test.py")
        assert result is True
        assert engine.session.edit_consent_mode == ConsentMode.ALWAYS

    @pytest.mark.asyncio
    async def test_file_consent_callback_never(self):
        engine = _make_engine()
        engine.consent_callback = AsyncMock(return_value=(False, ConsentResponse.NEVER))

        result = await request_file_edit_consent(engine, "/tmp/test.py")
        assert result is False
        assert engine.session.edit_consent_mode == ConsentMode.NEVER

    @pytest.mark.asyncio
    async def test_file_consent_callback_no(self):
        engine = _make_engine()
        engine.consent_callback = AsyncMock(return_value=(False, ConsentResponse.NO))

        result = await request_file_edit_consent(engine, "/tmp/test.py")
        assert result is False

    @pytest.mark.asyncio
    async def test_file_consent_callback_exception(self):
        engine = _make_engine()
        engine.consent_callback = AsyncMock(side_effect=RuntimeError("timeout"))

        result = await request_file_edit_consent(engine, "/tmp/test.py")
        assert result is False

    @pytest.mark.asyncio
    async def test_file_consent_creates_checkpoint_agent_mode(self):
        engine = _make_engine()
        engine._agent_mode = True
        engine._checkpoint_manager = MagicMock()
        engine.session.allowed_files = set()
        engine.session.edit_consent_mode = ConsentMode.ALWAYS

        await request_file_edit_consent(engine, "/tmp/test.py")
        engine.create_checkpoint.assert_called_once()

    @pytest.mark.asyncio
    async def test_file_consent_queues_event(self):
        engine = _make_engine()
        engine.consent_callback = AsyncMock(return_value=(True, ConsentResponse.YES))

        await request_file_edit_consent(engine, "/tmp/test.py")

        assert len(engine._event_queue) == 1
        evt = engine._event_queue[0]
        assert evt.type == EventType.CONSENT_REQUEST

    def test_classify_command(self):
        engine = _make_engine()
        engine._shell_config = {"safe_commands": ["ls", "cat"]}

        with patch("ppxai.engine.consent_ops.classify_shell_command", return_value=ShellRiskLevel.SAFE) as mock_classify:
            result = classify_command(engine, "ls -la")
            assert result == ShellRiskLevel.SAFE
            mock_classify.assert_called_once_with("ls -la", engine._shell_config)

    @pytest.mark.asyncio
    async def test_shell_consent_never_risk(self):
        engine = _make_engine()
        with patch("ppxai.engine.consent_ops.classify_shell_command", return_value=ShellRiskLevel.NEVER):
            result = await request_shell_consent(engine, "rm -rf /")
            assert result is False

    @pytest.mark.asyncio
    async def test_shell_consent_safe_risk(self):
        engine = _make_engine()
        with patch("ppxai.engine.consent_ops.classify_shell_command", return_value=ShellRiskLevel.SAFE):
            result = await request_shell_consent(engine, "ls")
            assert result is True

    @pytest.mark.asyncio
    async def test_shell_consent_dangerous_always_mode(self):
        engine = _make_engine()
        engine.session.shell_consent_mode = ConsentMode.ALWAYS
        with patch("ppxai.engine.consent_ops.classify_shell_command", return_value=ShellRiskLevel.DANGEROUS):
            result = await request_shell_consent(engine, "pip install foo")
            assert result is True

    @pytest.mark.asyncio
    async def test_shell_consent_dangerous_never_mode(self):
        engine = _make_engine()
        engine.session.shell_consent_mode = ConsentMode.NEVER
        with patch("ppxai.engine.consent_ops.classify_shell_command", return_value=ShellRiskLevel.DANGEROUS):
            result = await request_shell_consent(engine, "pip install foo")
            assert result is False

    @pytest.mark.asyncio
    async def test_shell_consent_already_allowed_command(self):
        engine = _make_engine()
        engine.session.allowed_commands = {"pip install foo"}
        with patch("ppxai.engine.consent_ops.classify_shell_command", return_value=ShellRiskLevel.DANGEROUS):
            result = await request_shell_consent(engine, "pip install foo")
            assert result is True

    @pytest.mark.asyncio
    async def test_shell_consent_no_callback_denies(self):
        engine = _make_engine()
        engine.shell_consent_callback = None
        with patch("ppxai.engine.consent_ops.classify_shell_command", return_value=ShellRiskLevel.DANGEROUS):
            result = await request_shell_consent(engine, "pip install foo")
            assert result is False

    @pytest.mark.asyncio
    async def test_shell_consent_callback_yes(self):
        engine = _make_engine()
        engine.shell_consent_callback = AsyncMock(return_value=(True, ConsentResponse.YES))
        with patch("ppxai.engine.consent_ops.classify_shell_command", return_value=ShellRiskLevel.DANGEROUS):
            result = await request_shell_consent(engine, "pip install foo")
            assert result is True
            assert "pip install foo" in engine.session.allowed_commands

    @pytest.mark.asyncio
    async def test_shell_consent_callback_always(self):
        engine = _make_engine()
        engine.shell_consent_callback = AsyncMock(return_value=(True, ConsentResponse.ALWAYS))
        with patch("ppxai.engine.consent_ops.classify_shell_command", return_value=ShellRiskLevel.DANGEROUS):
            result = await request_shell_consent(engine, "pip install foo")
            assert result is True
            assert engine.session.shell_consent_mode == ConsentMode.ALWAYS

    @pytest.mark.asyncio
    async def test_shell_consent_callback_exception(self):
        engine = _make_engine()
        engine.shell_consent_callback = AsyncMock(side_effect=RuntimeError("fail"))
        with patch("ppxai.engine.consent_ops.classify_shell_command", return_value=ShellRiskLevel.DANGEROUS):
            result = await request_shell_consent(engine, "pip install foo")
            assert result is False


# ===========================================================================
# TestSessionOps
# ===========================================================================

class TestSessionOps:
    """Tests for ppxai.engine.session_ops."""

    def test_restore_session_not_found(self):
        engine = _make_engine()
        engine.session.load.return_value = False

        result = restore_session(engine, "nonexistent")

        assert result["success"] is False
        assert "not found" in result["error"]

    def test_restore_session_success_minimal(self):
        engine = _make_engine()
        engine.session.load.return_value = True
        engine.session.metadata = {}
        engine.session.tools_enabled = False
        engine.session.working_dir = None
        engine.session.messages = [MagicMock(), MagicMock()]
        engine.provider_name = "openai"
        engine.model = "gpt-4"
        engine.tools_enabled = False
        engine.get_working_dir.return_value = "/home/user"

        result = restore_session(engine, "test-session")

        assert result["success"] is True
        assert result["message_count"] == 2
        engine.state.update.assert_called_once_with(session_id="test-session", session_name="test-session")

    def test_restore_session_restores_provider_and_model(self):
        engine = _make_engine()
        engine.session.load.return_value = True
        engine.session.metadata = {"provider": "perplexity", "model": "sonar-pro"}
        engine.session.tools_enabled = True
        engine.session.working_dir = None
        engine.session.messages = []
        engine.set_model.return_value = True

        result = restore_session(engine, "sess1")

        assert result["success"] is True
        engine.set_provider.assert_called_once_with("perplexity")
        engine.set_model.assert_called_with("sonar-pro", strict=True, reset_context=False)
        engine.enable_tools.assert_called_once()

    @patch("ppxai.engine.session_ops.get_default_model", return_value="gpt-4o")
    def test_restore_session_model_fallback(self, mock_default):
        engine = _make_engine()
        engine.session.load.return_value = True
        engine.session.metadata = {"provider": "openai", "model": "deleted-model"}
        engine.session.tools_enabled = False
        engine.session.working_dir = None
        engine.session.messages = []
        engine.set_model.side_effect = [False, True]  # first fails, fallback succeeds
        engine.provider_name = "openai"
        engine.provider = MagicMock()

        result = restore_session(engine, "sess1")

        assert result["success"] is True
        assert engine.set_model.call_count == 2

    @patch("ppxai.engine.session_ops.os.path.isdir", return_value=True)
    def test_restore_session_restores_working_dir(self, mock_isdir):
        engine = _make_engine()
        engine.session.load.return_value = True
        engine.session.metadata = {}
        engine.session.tools_enabled = False
        engine.session.working_dir = "/project/dir"
        engine.session.messages = []

        restore_session(engine, "sess1")

        engine.set_working_dir.assert_called_once_with("/project/dir")

    def test_get_history(self):
        engine = _make_engine()
        engine.session.get_messages_as_dicts.return_value = [{"role": "user", "content": "hi"}]

        result = get_history(engine)
        assert result == [{"role": "user", "content": "hi"}]

    def test_export_conversation(self):
        engine = _make_engine()
        engine.session.export.return_value = Path("/exports/chat.md")

        result = export_conversation(engine, "chat.md")
        assert result == Path("/exports/chat.md")
        engine.session.export.assert_called_once_with("chat.md")

    def test_export_answer_no_assistant_message(self):
        engine = _make_engine()
        engine.session.messages = []

        with pytest.raises(ValueError, match="No assistant response"):
            export_answer(engine)

    @patch("ppxai.engine.session_ops.EXPORTS_DIR")
    def test_export_answer_success(self, mock_exports_dir, tmp_path):
        mock_exports_dir.__truediv__ = lambda self, name: tmp_path / name

        msg = Message(role="assistant", content="Here is the answer.")
        engine = _make_engine()
        engine.session.messages = [msg]

        result = export_answer(engine, "answer.md")

        assert result == tmp_path / "answer.md"
        assert (tmp_path / "answer.md").read_text(encoding="utf-8") == "Here is the answer."

    @patch("ppxai.engine.session_ops.EXPORTS_DIR")
    def test_export_answer_auto_filename(self, mock_exports_dir, tmp_path):
        mock_exports_dir.__truediv__ = lambda self, name: tmp_path / name

        msg = Message(role="assistant", content="Auto named.")
        engine = _make_engine()
        engine.session.messages = [msg]

        result = export_answer(engine)

        assert result.name.startswith("answer_")
        assert result.name.endswith(".md")
        assert result.read_text(encoding="utf-8") == "Auto named."

    @patch("ppxai.engine.session_ops.EXPORTS_DIR")
    def test_export_answer_adds_md_extension(self, mock_exports_dir, tmp_path):
        mock_exports_dir.__truediv__ = lambda self, name: tmp_path / name

        msg = Message(role="assistant", content="Content")
        engine = _make_engine()
        engine.session.messages = [msg]

        result = export_answer(engine, "myfile")
        assert result.name == "myfile.md"

    @patch("ppxai.engine.session_ops.EXPORTS_DIR")
    def test_export_answer_finds_last_assistant(self, mock_exports_dir, tmp_path):
        mock_exports_dir.__truediv__ = lambda self, name: tmp_path / name

        user_msg = Message(role="user", content="question")
        first_asst = Message(role="assistant", content="first answer")
        second_asst = Message(role="assistant", content="second answer")
        engine = _make_engine()
        engine.session.messages = [user_msg, first_asst, user_msg, second_asst]

        result = export_answer(engine, "out.md")
        assert (tmp_path / "out.md").read_text(encoding="utf-8") == "second answer"

    def test_get_usage(self):
        engine = _make_engine()
        engine.session.get_usage.return_value = {"total_tokens": 100}

        assert get_usage(engine) == {"total_tokens": 100}

    def test_get_status(self):
        engine = _make_engine()
        engine.tools_enabled = True
        engine.tool_manager.list_tools.return_value = ["read_file", "write_file"]
        engine.session.messages = [MagicMock()]

        status = get_status(engine)

        assert status["provider"] == "openai"
        assert status["model"] == "gpt-4"
        assert status["tools_enabled"] is True
        assert status["tool_count"] == 2
        assert status["message_count"] == 1

    def test_get_status_tools_disabled(self):
        engine = _make_engine()
        engine.tools_enabled = False

        status = get_status(engine)
        assert status["tool_count"] == 0

    @patch("ppxai.engine.session_ops.get_model_context_limit", return_value=128000)
    def test_get_context_info(self, mock_limit):
        msg1 = Message(role="user", content="a" * 400)  # 100 tokens
        msg2 = Message(role="assistant", content="b" * 400)  # 100 tokens
        engine = _make_engine()
        engine.session.messages = [msg1, msg2]
        engine._injected_contexts = [{"name": "file.py", "size": 200}]

        info = get_context_info(engine)

        assert info["estimated_tokens"] == 200  # 800 chars // 4
        assert info["context_limit"] == 128000
        assert info["usage_percent"] == pytest.approx(200 / 128000 * 100)
        assert info["injected_tokens"] == 50  # 200 // 4
        assert info["message_count"] == 2
        assert info["total_chars"] == 800
        assert len(info["injected_contexts"]) == 1

    @patch("ppxai.engine.session_ops.get_model_context_limit", return_value=0)
    def test_get_context_info_zero_limit(self, mock_limit):
        engine = _make_engine()
        engine.session.messages = []
        engine._injected_contexts = []

        info = get_context_info(engine)
        assert info["usage_percent"] == 0

    def test_clear_injected_contexts_empty(self):
        engine = _make_engine()
        engine._injected_contexts = []

        assert clear_injected_contexts(engine) == 0

    def test_clear_injected_contexts_removes_injections(self):
        engine = _make_engine()
        engine._injected_contexts = [{"name": "a.py"}, {"name": "b.py"}]

        # Use a simple object instead of MagicMock so .content assignment sticks
        class FakeMsg:
            def __init__(self, role, content):
                self.role = role
                self.content = content

        msg1 = FakeMsg("user", 'Hello\n---\n**`@a.py`** (100 chars):\n```python\nprint("hi")\n```\n')
        msg2 = FakeMsg("assistant", "Response here")
        engine.session.messages = [msg1, msg2]

        result = clear_injected_contexts(engine)

        assert result == 2
        assert engine._injected_contexts == []
        # Injection markup should be stripped from user message
        assert "@a.py" not in msg1.content
        # Assistant message untouched
        assert msg2.content == "Response here"
