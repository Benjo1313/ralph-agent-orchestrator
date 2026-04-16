"""Tests for AgentRunner CLI subprocess and API dispatch."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

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
def anthropic_agent_config():
    return AgentConfig(
        type="api",
        provider="anthropic",
        model="claude-sonnet-4-6",
        description="Claude API",
        strengths=["code_review"],
    )


@pytest.fixture
def openai_agent_config():
    return AgentConfig(
        type="api",
        provider="openai",
        model="gpt-5",
        description="OpenAI API",
        strengths=["implementation"],
    )


class TestRunResult:
    def test_success(self):
        result = RunResult(success=True, output="Done", exit_code=0)
        assert result.success
        assert result.output == "Done"
        assert result.error is None
        assert result.exit_code == 0

    def test_failure(self):
        result = RunResult(success=False, error="Process exited with code 1", exit_code=1)
        assert not result.success
        assert result.error == "Process exited with code 1"
        assert result.exit_code == 1


class TestAgentRunnerCLI:
    async def test_run_cli_success(self, cli_agent_config):
        runner = AgentRunner(agent_config=cli_agent_config)

        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (b"Agent output here\n", b"")
        mock_proc.returncode = 0

        with patch(
            "ralph.agents.runner.asyncio.create_subprocess_exec",
            return_value=mock_proc,
        ):
            result = await runner.run(prompt="Add dark mode toggle to settings view")

        assert result.success
        assert result.output == "Agent output here\n"
        assert result.exit_code == 0

    async def test_run_cli_success_uses_stderr_when_stdout_empty(self, cli_agent_config):
        runner = AgentRunner(
            agent_config=cli_agent_config.model_copy(update={"prompt_mode": "argument"})
        )

        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (b"", b"Agent summary on stderr")
        mock_proc.returncode = 0

        with patch(
            "ralph.agents.runner.asyncio.create_subprocess_exec",
            return_value=mock_proc,
        ):
            result = await runner.run(prompt="Do something")

        assert result.success
        assert result.output == "Agent summary on stderr"

    async def test_run_cli_stdin_mode_writes_prompt_to_stdin(self, cli_agent_config):
        runner = AgentRunner(
            agent_config=cli_agent_config.model_copy(update={"prompt_mode": "stdin"})
        )

        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (b"ok", b"")
        mock_proc.returncode = 0

        with patch(
            "ralph.agents.runner.asyncio.create_subprocess_exec",
            return_value=mock_proc,
        ) as mock_exec:
            await runner.run(prompt="Do something over stdin")

        call_args = mock_exec.call_args.args
        call_kwargs = mock_exec.call_args.kwargs
        assert call_args == ("claude", "--print", "--output-format", "text")
        assert call_kwargs["stdin"] is not None
        mock_proc.communicate.assert_awaited_once_with(b"Do something over stdin")

    async def test_run_cli_passes_prompt(self, cli_agent_config):
        runner = AgentRunner(agent_config=cli_agent_config)

        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (b"ok", b"")
        mock_proc.returncode = 0

        with patch(
            "ralph.agents.runner.asyncio.create_subprocess_exec",
            return_value=mock_proc,
        ) as mock_exec:
            await runner.run(prompt="Do something", system_message="ignored for cli")

        call_args = mock_exec.call_args.args
        assert call_args[0] == "claude"
        assert "--print" in call_args
        assert "Do something" in call_args

    async def test_run_cli_nonzero_exit_is_failure(self, cli_agent_config):
        runner = AgentRunner(agent_config=cli_agent_config)

        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (b"", b"Error: something went wrong")
        mock_proc.returncode = 1

        with patch(
            "ralph.agents.runner.asyncio.create_subprocess_exec",
            return_value=mock_proc,
        ):
            result = await runner.run(prompt="Do something")

        assert not result.success
        assert result.error is not None
        assert "code 1" in result.error
        assert "stderr" in result.error
        assert result.exit_code == 1

    async def test_run_cli_nonzero_exit_surfaces_stdout_and_mode(self, cli_agent_config):
        runner = AgentRunner(
            agent_config=cli_agent_config.model_copy(update={"prompt_mode": "stdin"})
        )

        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (b"partial output", b"fatal error")
        mock_proc.returncode = 2

        with patch(
            "ralph.agents.runner.asyncio.create_subprocess_exec",
            return_value=mock_proc,
        ):
            result = await runner.run(prompt="Do something")

        assert not result.success
        assert "Prompt mode: stdin" in result.error
        assert "stdout: partial output" in result.error
        assert "stderr: fatal error" in result.error
        assert result.exit_code == 2

    async def test_run_cli_exception_is_failure(self, cli_agent_config):
        runner = AgentRunner(agent_config=cli_agent_config)

        with patch(
            "ralph.agents.runner.asyncio.create_subprocess_exec",
            side_effect=FileNotFoundError("claude not found"),
        ):
            result = await runner.run(prompt="Do something")

        assert not result.success
        assert "not found on PATH" in result.error
        assert "claude" in result.error


class TestAgentRunnerAPI:
    async def test_run_api_anthropic_success(self, anthropic_agent_config, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        runner = AgentRunner(agent_config=anthropic_agent_config)

        response = MagicMock()
        response.content = [MagicMock(text="Claude says hi")]
        client = MagicMock()
        client.messages.create = AsyncMock(return_value=response)

        with patch("ralph.agents.runner.AsyncAnthropic", return_value=client):
            result = await runner.run(prompt="Review this code", system_message="Repo context")

        assert result.success
        assert result.output == "Claude says hi"
        call_kwargs = client.messages.create.call_args.kwargs
        assert call_kwargs["system"] == "Repo context"
        assert call_kwargs["messages"] == [{"role": "user", "content": "Review this code"}]

    async def test_run_api_openai_success(self, openai_agent_config, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        runner = AgentRunner(agent_config=openai_agent_config)

        response = MagicMock()
        response.choices = [MagicMock(message=MagicMock(content="OpenAI says hi"))]
        client = MagicMock()
        client.chat.completions.create = AsyncMock(return_value=response)

        with patch("ralph.agents.runner.AsyncOpenAI", return_value=client):
            result = await runner.run(prompt="Implement this", system_message="Repo context")

        assert result.success
        assert result.output == "OpenAI says hi"
        call_kwargs = client.chat.completions.create.call_args.kwargs
        assert call_kwargs["messages"][0] == {"role": "system", "content": "Repo context"}
        assert call_kwargs["messages"][1] == {"role": "user", "content": "Implement this"}

    async def test_run_api_anthropic_missing_key(self, anthropic_agent_config, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        runner = AgentRunner(agent_config=anthropic_agent_config)

        result = await runner.run(prompt="Review this code")

        assert not result.success
        assert "ANTHROPIC_API_KEY" in result.error

    async def test_run_api_openai_missing_key(self, openai_agent_config, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        runner = AgentRunner(agent_config=openai_agent_config)

        result = await runner.run(prompt="Implement this")

        assert not result.success
        assert "OPENAI_API_KEY" in result.error

    async def test_run_api_anthropic_sdk_error(self, anthropic_agent_config, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        runner = AgentRunner(agent_config=anthropic_agent_config)

        client = MagicMock()
        client.messages.create = AsyncMock(side_effect=RuntimeError("Anthropic boom"))

        with patch("ralph.agents.runner.AsyncAnthropic", return_value=client):
            result = await runner.run(prompt="Review this code")

        assert not result.success
        assert result.error == "Anthropic boom"

    async def test_run_api_openai_sdk_error(self, openai_agent_config, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        runner = AgentRunner(agent_config=openai_agent_config)

        client = MagicMock()
        client.chat.completions.create = AsyncMock(side_effect=RuntimeError("OpenAI boom"))

        with patch("ralph.agents.runner.AsyncOpenAI", return_value=client):
            result = await runner.run(prompt="Implement this")

        assert not result.success
        assert result.error == "OpenAI boom"

    async def test_run_api_unknown_provider(self):
        runner = AgentRunner(
            agent_config=AgentConfig(
                type="api",
                provider="azure",
                model="gpt-4.1",
                description="Unknown API",
            )
        )

        result = await runner.run(prompt="Do something")

        assert not result.success
        assert "azure" in result.error
