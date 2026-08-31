"""Tests for the v1.18.5 read_preview_log tool + /preview logs slash command.

Covers:
- Tool: missing log dir / missing log file / empty log returns sane message
- Tool: happy path returns parsed JSONL with cursor metadata
- Tool: `since` cursor only returns new lines + handles rotation
  (cursor past EOF → reset to 0)
- Tool: `filter` regex narrows results; invalid regex falls back to substring
- Tool: `pid` selects specific backend; absence falls back to most-recent-mtime
- Tool: backend_alive correctly reflects pid liveness
- Tool: malformed JSONL line surfaces as `{type: "raw", line: ...}`
- Slash command: `/preview logs` and `/preview logs 50` route to the tool
- Drain task: emits structured JSONL records (drain_start, stdout, drain_end)
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from ppxai.engine.tools.builtin import preview_log
from ppxai.engine.tools.builtin.preview_log import read_preview_log

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_logs_dir(tmp_path, monkeypatch):
    """Patch PREVIEW_LOGS_DIR to a tmp_path so tests don't touch real logs."""
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()
    monkeypatch.setattr(preview_log, "PREVIEW_LOGS_DIR", logs_dir)
    return logs_dir


def _write_jsonl_log(path: Path, records: list[dict]) -> None:
    """Helper: write a list of dicts as JSONL."""
    with path.open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def _sample_records(pid: int = 12345) -> list[dict]:
    return [
        {"ts": "2026-05-10T22:00:00.000Z", "type": "drain_start", "pid": pid},
        {"ts": "2026-05-10T22:00:01.123Z", "type": "stdout", "pid": pid,
         "line": "INFO:     Started server process"},
        {"ts": "2026-05-10T22:00:02.456Z", "type": "stdout", "pid": pid,
         "line": "INFO:     Application startup complete"},
        {"ts": "2026-05-10T22:00:30.789Z", "type": "stdout", "pid": pid,
         "line": "ERROR:    GET /tasks 500"},
        {"ts": "2026-05-10T22:01:00.000Z", "type": "drain_end", "pid": pid},
    ]


# ---------------------------------------------------------------------------
# Empty / missing cases
# ---------------------------------------------------------------------------


class TestReadPreviewLogEmptyCases:
    def test_no_logs_dir(self, monkeypatch, tmp_path):
        monkeypatch.setattr(
            preview_log, "PREVIEW_LOGS_DIR", tmp_path / "does-not-exist"
        )
        result = read_preview_log()
        assert "No active preview backend log found" in result

    def test_logs_dir_empty(self, fake_logs_dir):
        result = read_preview_log()
        assert "No active preview backend log found" in result

    def test_specific_pid_not_found(self, fake_logs_dir):
        result = read_preview_log(pid=99999)
        assert "No preview backend log found for pid 99999" in result

    def test_log_file_empty(self, fake_logs_dir):
        log_path = fake_logs_dir / "preview-backend-12345.log"
        log_path.write_text("", encoding="utf-8")
        result = read_preview_log()
        # Empty log: header is shown, body says "(log is empty)".
        assert "preview-backend-12345.log" in result
        assert "(log is empty)" in result


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


class TestReadPreviewLogHappyPath:
    def test_returns_all_lines_under_default_limit(self, fake_logs_dir):
        log_path = fake_logs_dir / "preview-backend-12345.log"
        _write_jsonl_log(log_path, _sample_records())
        result = read_preview_log()
        assert "preview-backend-12345.log" in result
        assert "drain_start pid=12345" in result
        assert "Started server process" in result
        assert "Application startup complete" in result
        assert "ERROR:    GET /tasks 500" in result
        assert "drain_end pid=12345" in result
        assert '"lines_returned": 5' in result

    def test_lines_param_caps_results(self, fake_logs_dir):
        log_path = fake_logs_dir / "preview-backend-12345.log"
        _write_jsonl_log(log_path, _sample_records())
        result = read_preview_log(lines=2)
        # Last 2 records — drain_end + the ERROR before it
        assert '"lines_returned": 2' in result
        assert "drain_end" in result
        assert "ERROR" in result
        # Earlier records gone from the visible body
        assert "drain_start" not in result.split("--- structured payload")[0]

    def test_payload_contains_next_since_cursor(self, fake_logs_dir):
        log_path = fake_logs_dir / "preview-backend-12345.log"
        _write_jsonl_log(log_path, _sample_records())
        result = read_preview_log()
        # Extract the structured payload
        marker = "--- structured payload"
        idx = result.index(marker)
        payload_text = result[idx + len(marker):].strip().lstrip("(for tool-call cursor) ---").strip()
        payload = json.loads(payload_text)
        assert "next_since" in payload
        assert int(payload["next_since"]) > 0
        assert payload["log_file"].endswith("preview-backend-12345.log")
        assert payload["backend_pid"] == 12345
        assert payload["lines_returned"] == 5


# ---------------------------------------------------------------------------
# Cursor semantics
# ---------------------------------------------------------------------------


class TestReadPreviewLogCursor:
    def test_since_returns_only_new_lines(self, fake_logs_dir):
        log_path = fake_logs_dir / "preview-backend-12345.log"
        # Initial 3 lines
        _write_jsonl_log(log_path, _sample_records()[:3])

        # First read → get cursor
        first = read_preview_log()
        marker = "--- structured payload"
        payload_first = json.loads(first.split(marker)[1].split("---", 1)[1])
        cursor1 = payload_first["next_since"]

        # Append more lines
        with log_path.open("a", encoding="utf-8") as f:
            for r in _sample_records()[3:]:
                f.write(json.dumps(r) + "\n")

        # Second read with cursor → only the new lines
        second = read_preview_log(since=cursor1)
        payload_second = json.loads(second.split(marker)[1].split("---", 1)[1])
        assert payload_second["lines_returned"] == 2  # ERROR + drain_end
        types = {ln["type"] for ln in payload_second["lines"]}
        assert "drain_end" in types

    def test_since_past_eof_resets_to_start(self, fake_logs_dir):
        """When the file got rotated/truncated and the cursor is now past
        EOF, gracefully restart from offset 0 rather than erroring out."""
        log_path = fake_logs_dir / "preview-backend-12345.log"
        _write_jsonl_log(log_path, _sample_records())
        size = log_path.stat().st_size
        # Cursor far past end-of-file → graceful reset
        result = read_preview_log(since=str(size + 9999))
        marker = "--- structured payload"
        payload = json.loads(result.split(marker)[1].split("---", 1)[1])
        # All 5 records returned
        assert payload["lines_returned"] == 5

    def test_invalid_since_string_falls_back_to_zero(self, fake_logs_dir):
        log_path = fake_logs_dir / "preview-backend-12345.log"
        _write_jsonl_log(log_path, _sample_records())
        result = read_preview_log(since="not-a-number")
        marker = "--- structured payload"
        payload = json.loads(result.split(marker)[1].split("---", 1)[1])
        assert payload["lines_returned"] == 5


# ---------------------------------------------------------------------------
# Filter
# ---------------------------------------------------------------------------


class TestReadPreviewLogFilter:
    def test_regex_filter_narrows_results(self, fake_logs_dir):
        log_path = fake_logs_dir / "preview-backend-12345.log"
        _write_jsonl_log(log_path, _sample_records())
        result = read_preview_log(filter=r"ERROR|drain")
        marker = "--- structured payload"
        payload = json.loads(result.split(marker)[1].split("---", 1)[1])
        # 3 records match: drain_start, ERROR, drain_end
        assert payload["lines_returned"] == 3

    def test_invalid_regex_falls_back_to_substring(self, fake_logs_dir):
        log_path = fake_logs_dir / "preview-backend-12345.log"
        _write_jsonl_log(log_path, _sample_records())
        # `[` is invalid regex — should fall back to substring search
        result = read_preview_log(filter="[")
        marker = "--- structured payload"
        payload = json.loads(result.split(marker)[1].split("---", 1)[1])
        # No record contains `[` substring → 0 results, not a crash
        assert payload["lines_returned"] == 0


# ---------------------------------------------------------------------------
# Pid + most-recent selection
# ---------------------------------------------------------------------------


class TestReadPreviewLogPidSelection:
    def test_specific_pid(self, fake_logs_dir):
        log1 = fake_logs_dir / "preview-backend-1111.log"
        log2 = fake_logs_dir / "preview-backend-2222.log"
        _write_jsonl_log(log1, _sample_records(pid=1111))
        _write_jsonl_log(log2, _sample_records(pid=2222))
        result = read_preview_log(pid=1111)
        assert "preview-backend-1111.log" in result
        assert "pid=1111" in result

    def test_default_picks_most_recent_mtime(self, fake_logs_dir):
        log_old = fake_logs_dir / "preview-backend-1111.log"
        log_new = fake_logs_dir / "preview-backend-2222.log"
        _write_jsonl_log(log_old, _sample_records(pid=1111))
        _write_jsonl_log(log_new, _sample_records(pid=2222))
        # Make log_new more recent
        old_time = log_old.stat().st_mtime
        os.utime(log_new, (old_time + 100, old_time + 100))
        result = read_preview_log()
        assert "preview-backend-2222.log" in result


# ---------------------------------------------------------------------------
# Backend liveness
# ---------------------------------------------------------------------------


class TestBackendAlive:
    def test_dead_pid_reports_alive_false(self, fake_logs_dir):
        log_path = fake_logs_dir / "preview-backend-99999.log"
        _write_jsonl_log(log_path, _sample_records(pid=99999))
        result = read_preview_log()
        marker = "--- structured payload"
        payload = json.loads(result.split(marker)[1].split("---", 1)[1])
        assert payload["backend_alive"] is False
        assert payload["backend_pid"] == 99999

    def test_alive_pid_reports_alive_true(self, fake_logs_dir):
        # Use this Python process's own pid; it's definitely alive.
        my_pid = os.getpid()
        log_path = fake_logs_dir / f"preview-backend-{my_pid}.log"
        _write_jsonl_log(log_path, _sample_records(pid=my_pid))
        result = read_preview_log()
        marker = "--- structured payload"
        payload = json.loads(result.split(marker)[1].split("---", 1)[1])
        assert payload["backend_alive"] is True
        assert payload["backend_pid"] == my_pid


# ---------------------------------------------------------------------------
# Malformed lines
# ---------------------------------------------------------------------------


class TestReadPreviewLogMalformed:
    def test_non_json_line_surfaces_as_raw(self, fake_logs_dir):
        log_path = fake_logs_dir / "preview-backend-12345.log"
        with log_path.open("w", encoding="utf-8") as f:
            f.write('{"ts": "2026-05-10T22:00:00.000Z", "type": "stdout", "pid": 12345, "line": "ok"}\n')
            f.write('this is not json\n')
            f.write('{"ts": "2026-05-10T22:00:02.000Z", "type": "stdout", "pid": 12345, "line": "still ok"}\n')
        result = read_preview_log()
        marker = "--- structured payload"
        payload = json.loads(result.split(marker)[1].split("---", 1)[1])
        assert payload["lines_returned"] == 3
        types = [ln["type"] for ln in payload["lines"]]
        assert "raw" in types  # the malformed line came through as raw


# ---------------------------------------------------------------------------
# Slash command wrapper
# ---------------------------------------------------------------------------


class TestPreviewLogsSlashCommand:
    def _make_context(self, tmp_path):
        from ppxai.commands.protocol import CommandContext

        ec = MagicMock()
        ec.get_working_dir = MagicMock(return_value=str(tmp_path))
        ctx = MagicMock(spec=CommandContext)
        ctx.engine_client = ec
        ctx.cwd = str(tmp_path)
        return ctx

    def test_logs_subcommand_invokes_tool(self, tmp_path, fake_logs_dir):
        from ppxai.commands.display import handle_preview

        log_path = fake_logs_dir / "preview-backend-12345.log"
        _write_jsonl_log(log_path, _sample_records())

        ctx = self._make_context(tmp_path)
        result = handle_preview(ctx, "logs")
        assert "preview-backend-12345.log" in result.message
        assert "Started server process" in result.message
        assert result.metadata.get("action") == "preview-logs"
        assert result.metadata.get("lines_requested") == 100

    def test_logs_with_explicit_count(self, tmp_path, fake_logs_dir):
        from ppxai.commands.display import handle_preview

        log_path = fake_logs_dir / "preview-backend-12345.log"
        _write_jsonl_log(log_path, _sample_records())

        ctx = self._make_context(tmp_path)
        result = handle_preview(ctx, "logs 2")
        assert result.metadata.get("lines_requested") == 2
        # Only last 2 records visible
        assert "drain_end" in result.message
        # And the structured payload reflects the cap
        assert '"lines_returned": 2' in result.message

    def test_logs_with_no_active_preview(self, tmp_path, fake_logs_dir):
        from ppxai.commands.display import handle_preview

        ctx = self._make_context(tmp_path)
        result = handle_preview(ctx, "logs")
        # Empty logs dir → tool's "no preview backend" message
        assert "No active preview backend log" in result.message


# ---------------------------------------------------------------------------
# Drain task: JSONL emission
# ---------------------------------------------------------------------------


class TestDrainTaskEmitsJsonl:
    """Verify the v1.18.5 drain task writes structured JSONL records."""

    @pytest.mark.asyncio
    async def test_drain_writes_jsonl_records(self, tmp_path):
        from ppxai.engine.preview_backend import drain_backend_output as _drain_backend_output

        proc = MagicMock()
        proc.pid = 88888
        lines = iter([
            b"INFO:     Started server\n",
            b"INFO:     Application startup complete\n",
            b"",  # EOF
        ])
        async def readline():
            return next(lines)
        proc.stdout = MagicMock()
        proc.stdout.readline = readline

        log_path = tmp_path / "preview-backend-88888.log"
        await _drain_backend_output(proc, log_path=log_path)

        records = []
        for raw in log_path.read_text(encoding="utf-8").splitlines():
            if raw.strip():
                records.append(json.loads(raw))

        # Expected: drain_start, 2 stdout, drain_end
        assert len(records) == 4
        assert records[0]["type"] == "drain_start"
        assert records[0]["pid"] == 88888
        assert records[1]["type"] == "stdout"
        assert records[1]["line"] == "INFO:     Started server"
        assert records[2]["type"] == "stdout"
        assert records[2]["line"] == "INFO:     Application startup complete"
        assert records[3]["type"] == "drain_end"
        # Every record has a ts field
        for r in records:
            assert "ts" in r and r["ts"]
