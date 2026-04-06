"""Tests for AgentRunner — CLI subprocess and API dispatch."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from ralph.agents.runner import AgentRunner, RunResult
from ralph.config.schema import AgentConfig


@pytest.fixture
def cli_agent_config():
    return AgentConfig(
        type="cli",
        command="claude",
        flags=["--print", "--output-format", "text"],
        description="Claude Code",
        strengths=["architecture"],
    )


@pytest.fixture
def api_agent_config():
    return AgentConfig(
        type="api",
        provider="anthropic",
        model="claude-sonnet-4-6",
        description="Claude API",
        strengths=["code_review"],
    )


class TestRunResult:
    def test_success(self):
        r = RunResult(success=True, output="Done")
        assert r.success
        assert r.output == "Done"
        assert r.error is None

    def test_failure(self):
        r = RunResult(success=False, error="Process exited with code 1")
        assert not r.success
        assert r.error == "Process exited with code 1"


class TestAgentRunnerCLI:
    async def test_run_cli_success(self, cli_agent_config):
        runner = AgentRunner(agent_config=cli_agent_config)

        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (b"Agent output here\n", b"")
        mock_proc.returncode = 0

        with patch("ralph.agents.runner.asyncio.create_subprocess_exec", return_value=mock_proc) as mock_exec:
            result = await runner.run(prompt="Add dark mode toggle to settings view")

        assert result.success
        assert result.output == "Agent output here\n"

    async def test_run_cli_passes_prompt(self, cli_agent_config):
        runner = AgentRunner(agent_config=cli_agent_config)

        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (b"ok", b"")
        mock_proc.returncode = 0

        with patch("ralph.agents.runner.asyncio.create_subprocess_exec", return_value=mock_proc) as mock_exec:
            await runner.run(prompt="Do something")

        call_args = mock_exec.call_args.args
        # command + flags + prompt as final arg
        assert call_args[0] == "claude"
        assert "--print" in call_args
        assert "Do something" in call_args

    async def test_run_cli_nonzero_exit_is_failure(self, cli_agent_config):
        runner = AgentRunner(agent_config=cli_agent_config)

        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (b"", b"Error: something went wrong")
        mock_proc.returncode = 1

        with patch("ralph.agents.runner.asyncio.create_subprocess_exec", return_value=mock_proc):
            result = await runner.run(prompt="Do something")

        assert not result.success
        assert result.error is not None
        assert "1" in result.error  # exit code mentioned

    async def test_run_cli_exception_is_failure(self, cli_agent_config):
        runner = AgentRunner(agent_config=cli_agent_config)

        with patch("ralph.agents.runner.asyncio.create_subprocess_exec", side_effect=FileNotFoundError("claude not found")):
            result = await runner.run(prompt="Do something")

        assert not result.success
        assert "claude not found" in result.error

    async def test_run_cli_captures_stderr_on_failure(self, cli_agent_config):
        runner = AgentRunner(agent_config=cli_agent_config)

        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (b"", b"stderr: fatal error")
        mock_proc.returncode = 2

        with patch("ralph.agents.runner.asyncio.create_subprocess_exec", return_value=mock_proc):
            result = await runner.run(prompt="Do something")

        assert not result.success
        assert "stderr: fatal error" in result.error


class TestAgentRunnerAPI:
    async def test_run_api_unsupported_provider_fails(self, api_agent_config):
        runner = AgentRunner(agent_config=api_agent_config)
        result = await runner.run(prompt="Review this code")
        assert not result.success
        assert "anthropic" in result.error.lower() or "not supported" in result.error.lower()
