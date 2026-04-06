"""Integration tests for ralph run → orchestrator loop."""
import textwrap
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from click.testing import CliRunner

from ralph.cli.main import cli
from ralph.agents.runner import RunResult


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def global_config(tmp_path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text(textwrap.dedent("""\
        orchestrator:
          model: gemma4:27b
          provider: ollama
          endpoint: http://localhost:11434
        agents:
          claude_code:
            type: cli
            command: claude
            flags: ["--print"]
            description: "Claude Code"
            strengths: ["architecture"]
        routing:
          rules:
            - task_type: architecture
              prefer: claude_code
        skills: {}
    """))
    return cfg


class TestRunIntegration:
    def test_run_dry_run_skips_dispatch(self, runner, global_config, tmp_path):
        result = runner.invoke(
            cli,
            ["--config", str(global_config), "--project-dir", str(tmp_path),
             "run", "--dry-run", "add dark mode toggle"],
        )
        assert result.exit_code == 0
        assert "DRY RUN" in result.output
        assert "add dark mode toggle" in result.output

    def test_run_dispatches_to_agent(self, runner, global_config, tmp_path):
        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (b"Feature added.", b"")
        mock_proc.returncode = 0

        with patch("ralph.agents.runner.asyncio.create_subprocess_exec", return_value=mock_proc):
            result = runner.invoke(
                cli,
                ["--config", str(global_config), "--project-dir", str(tmp_path),
                 "run", "add dark mode toggle"],
            )

        assert result.exit_code == 0
        assert "done" in result.output.lower() or "complete" in result.output.lower() or "Feature added" in result.output

    def test_run_agent_failure_exits_nonzero(self, runner, global_config, tmp_path):
        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (b"", b"Agent crashed")
        mock_proc.returncode = 1

        with patch("ralph.agents.runner.asyncio.create_subprocess_exec", return_value=mock_proc):
            result = runner.invoke(
                cli,
                ["--config", str(global_config), "--project-dir", str(tmp_path),
                 "run", "add dark mode toggle"],
            )

        assert result.exit_code != 0

    def test_run_missing_config_exits_nonzero(self, runner, tmp_path):
        result = runner.invoke(
            cli,
            ["--config", str(tmp_path / "missing.yaml"), "--project-dir", str(tmp_path),
             "run", "add dark mode toggle"],
        )
        assert result.exit_code != 0

    def test_run_fresh_clears_previous_state(self, runner, global_config, tmp_path):
        # Seed a fake state file
        ralph_dir = tmp_path / ".ralph"
        ralph_dir.mkdir()
        (ralph_dir / "state.json").write_text('{"session_id": "old", "goal": "old", "tasks": {}}')

        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (b"ok", b"")
        mock_proc.returncode = 0

        with patch("ralph.agents.runner.asyncio.create_subprocess_exec", return_value=mock_proc):
            result = runner.invoke(
                cli,
                ["--config", str(global_config), "--project-dir", str(tmp_path),
                 "run", "--fresh", "new task"],
            )

        assert result.exit_code == 0
        # Old state should be gone / overwritten with new session
        import json
        new_state = json.loads((ralph_dir / "state.json").read_text())
        assert new_state["goal"] == "new task"
