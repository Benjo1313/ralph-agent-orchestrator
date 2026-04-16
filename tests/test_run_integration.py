"""Integration tests for `ralph run` through the orchestrator loop."""
import json
import textwrap
from unittest.mock import AsyncMock, patch

import pytest
from click.testing import CliRunner

from ralph.cli.main import cli
from ralph.core.evaluator import EvalDecision, Verdict
from ralph.core.task_graph import Task, TaskGraph


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def global_config(tmp_path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        textwrap.dedent(
            """\
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
            """
        )
    )
    return cfg


def planned_graph(goal: str) -> TaskGraph:
    graph = TaskGraph(session_id="planned-session", goal=goal)
    return graph.with_task(
        Task(
            id="t1",
            description=goal,
            task_type="implementation",
            agent="claude_code",
            acceptance_criteria="Task completes successfully",
        )
    )


def resumable_graph() -> TaskGraph:
    graph = TaskGraph(session_id="resume-session", goal="finish dark mode")
    graph = graph.with_task(
        Task(
            id="t1",
            description="Write tests",
            task_type="test_writing",
            agent="claude_code",
            acceptance_criteria="Tests cover the new behavior",
            status="done",
            result={
                "success": True,
                "output": "tests written",
                "exit_code": 0,
            },
        )
    )
    return graph.with_task(
        Task(
            id="t2",
            description="Implement dark mode",
            task_type="implementation",
            agent="claude_code",
            dependencies=["t1"],
            acceptance_criteria="Feature works",
        )
    )


class TestRunIntegration:
    def test_run_dry_run_skips_dispatch(self, runner, global_config, tmp_path):
        result = runner.invoke(
            cli,
            [
                "--config",
                str(global_config),
                "--project-dir",
                str(tmp_path),
                "run",
                "--dry-run",
                "add dark mode toggle",
            ],
        )
        assert result.exit_code == 0
        assert "DRY RUN" in result.output
        assert "add dark mode toggle" in result.output

    def test_run_dispatches_to_agent(self, runner, global_config, tmp_path):
        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (b"Feature added.", b"")
        mock_proc.returncode = 0

        planner_patch = patch(
            "ralph.cli.main.Planner.plan",
            new=AsyncMock(return_value=planned_graph("add dark mode toggle")),
        )
        evaluator_patch = patch(
            "ralph.cli.main.Evaluator.evaluate",
            new=AsyncMock(return_value=EvalDecision(verdict=Verdict.PASS, reason="done")),
        )
        with (
            planner_patch,
            evaluator_patch,
            patch("ralph.agents.runner.asyncio.create_subprocess_exec", return_value=mock_proc),
        ):
            result = runner.invoke(
                cli,
                [
                    "--config",
                    str(global_config),
                    "--project-dir",
                    str(tmp_path),
                    "run",
                    "add dark mode toggle",
                ],
            )

        assert result.exit_code == 0
        assert "complete" in result.output.lower()
        journal_files = list((tmp_path / ".ralph" / "journal").glob("*.md"))
        assert len(journal_files) == 1
        assert "add dark mode toggle" in journal_files[0].read_text()

    def test_run_agent_failure_exits_nonzero(self, runner, global_config, tmp_path):
        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (b"", b"Agent crashed")
        mock_proc.returncode = 1

        planner_patch = patch(
            "ralph.cli.main.Planner.plan",
            new=AsyncMock(return_value=planned_graph("add dark mode toggle")),
        )
        evaluator_patch = patch(
            "ralph.cli.main.Evaluator.evaluate",
            new=AsyncMock(
                return_value=EvalDecision(verdict=Verdict.ESCALATE, reason="Agent crashed")
            ),
        )
        with (
            planner_patch,
            evaluator_patch,
            patch("ralph.agents.runner.asyncio.create_subprocess_exec", return_value=mock_proc),
        ):
            result = runner.invoke(
                cli,
                [
                    "--config",
                    str(global_config),
                    "--project-dir",
                    str(tmp_path),
                    "run",
                    "add dark mode toggle",
                ],
            )

        assert result.exit_code != 0
        assert "Escalated" in result.output

    def test_run_prefixes_matching_cli_skill(self, runner, tmp_path):
        config_path = tmp_path / "config.yaml"
        config_path.write_text(
            textwrap.dedent(
                """\
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
                    - task_type: implementation
                      prefer: claude_code
                skills:
                  tdd:
                    agent: claude_code
                    invoke: "/tdd"
                    use_when: ["implementation"]
                """
            )
        )

        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (b"Feature added.", b"")
        mock_proc.returncode = 0

        planner_patch = patch(
            "ralph.cli.main.Planner.plan",
            new=AsyncMock(return_value=planned_graph("add dark mode toggle")),
        )
        evaluator_patch = patch(
            "ralph.cli.main.Evaluator.evaluate",
            new=AsyncMock(return_value=EvalDecision(verdict=Verdict.PASS, reason="done")),
        )
        with (
            planner_patch,
            evaluator_patch,
            patch(
                "ralph.agents.runner.asyncio.create_subprocess_exec",
                return_value=mock_proc,
            ) as create_subprocess,
        ):
            result = runner.invoke(
                cli,
                [
                    "--config",
                    str(config_path),
                    "--project-dir",
                    str(tmp_path),
                    "run",
                    "add dark mode toggle",
                ],
            )

        assert result.exit_code == 0
        prompt = create_subprocess.await_args.args[-1]
        assert prompt.startswith("/tdd\n\n")
        assert "Task:\nadd dark mode toggle" in prompt

    def test_run_missing_config_exits_nonzero(self, runner, tmp_path):
        result = runner.invoke(
            cli,
            [
                "--config",
                str(tmp_path / "missing.yaml"),
                "--project-dir",
                str(tmp_path),
                "run",
                "add dark mode toggle",
            ],
        )
        assert result.exit_code != 0

    def test_run_resume_uses_saved_state(self, runner, global_config, tmp_path):
        ralph_dir = tmp_path / ".ralph"
        ralph_dir.mkdir()
        (ralph_dir / "state.json").write_text(resumable_graph().model_dump_json(indent=2))

        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (b"implemented", b"")
        mock_proc.returncode = 0

        evaluator_patch = patch(
            "ralph.cli.main.Evaluator.evaluate",
            new=AsyncMock(return_value=EvalDecision(verdict=Verdict.PASS, reason="done")),
        )
        with (
            evaluator_patch,
            patch(
                "ralph.agents.runner.asyncio.create_subprocess_exec",
                return_value=mock_proc,
            ) as create_subprocess,
        ):
            result = runner.invoke(
                cli,
                [
                    "--config",
                    str(global_config),
                    "--project-dir",
                    str(tmp_path),
                    "run",
                    "--resume",
                ],
            )

        assert result.exit_code == 0
        assert "Resuming: finish dark mode" in result.output
        prompt = create_subprocess.await_args.args[-1]
        assert "Goal: finish dark mode" in prompt
        assert "Task:\nImplement dark mode" in prompt

        final_state = json.loads((ralph_dir / "state.json").read_text())
        assert final_state["tasks"]["t2"]["status"] == "done"

    def test_run_resume_missing_state_exits_nonzero(self, runner, global_config, tmp_path):
        result = runner.invoke(
            cli,
            [
                "--config",
                str(global_config),
                "--project-dir",
                str(tmp_path),
                "run",
                "--resume",
            ],
        )

        assert result.exit_code != 0
        assert "No saved state found" in result.output

    def test_run_rejects_new_task_when_saved_session_in_progress(
        self,
        runner,
        global_config,
        tmp_path,
    ):
        ralph_dir = tmp_path / ".ralph"
        ralph_dir.mkdir()
        (ralph_dir / "state.json").write_text(resumable_graph().model_dump_json(indent=2))

        result = runner.invoke(
            cli,
            [
                "--config",
                str(global_config),
                "--project-dir",
                str(tmp_path),
                "run",
                "brand new task",
            ],
        )

        assert result.exit_code != 0
        assert "Use --resume to continue it or --fresh TASK to start over" in result.output

    def test_run_fresh_clears_previous_state(self, runner, global_config, tmp_path):
        ralph_dir = tmp_path / ".ralph"
        ralph_dir.mkdir()
        (ralph_dir / "state.json").write_text('{"session_id": "old", "goal": "old", "tasks": {}}')

        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (b"ok", b"")
        mock_proc.returncode = 0

        planner_patch = patch(
            "ralph.cli.main.Planner.plan",
            new=AsyncMock(return_value=planned_graph("new task")),
        )
        evaluator_patch = patch(
            "ralph.cli.main.Evaluator.evaluate",
            new=AsyncMock(return_value=EvalDecision(verdict=Verdict.PASS, reason="done")),
        )
        with (
            planner_patch,
            evaluator_patch,
            patch("ralph.agents.runner.asyncio.create_subprocess_exec", return_value=mock_proc),
        ):
            result = runner.invoke(
                cli,
                [
                    "--config",
                    str(global_config),
                    "--project-dir",
                    str(tmp_path),
                    "run",
                    "--fresh",
                    "new task",
                ],
            )

        assert result.exit_code == 0
        new_state = json.loads((ralph_dir / "state.json").read_text())
        assert new_state["goal"] == "new task"

    def test_run_supports_cli_stdin_prompt_mode(self, runner, tmp_path):
        config_path = tmp_path / "config.yaml"
        config_path.write_text(
            textwrap.dedent(
                """\
                orchestrator:
                  model: gemma4:27b
                  provider: ollama
                  endpoint: http://localhost:11434
                agents:
                  claude_code:
                    type: cli
                    command: claude
                    flags: ["--print"]
                    prompt_mode: stdin
                    description: "Claude Code"
                    strengths: ["architecture"]
                routing:
                  rules:
                    - task_type: implementation
                      prefer: claude_code
                skills: {}
                """
            )
        )

        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (b"Feature added.", b"")
        mock_proc.returncode = 0

        planner_patch = patch(
            "ralph.cli.main.Planner.plan",
            new=AsyncMock(return_value=planned_graph("add dark mode toggle")),
        )
        evaluator_patch = patch(
            "ralph.cli.main.Evaluator.evaluate",
            new=AsyncMock(return_value=EvalDecision(verdict=Verdict.PASS, reason="done")),
        )
        with (
            planner_patch,
            evaluator_patch,
            patch(
                "ralph.agents.runner.asyncio.create_subprocess_exec",
                return_value=mock_proc,
            ) as create_subprocess,
        ):
            result = runner.invoke(
                cli,
                [
                    "--config",
                    str(config_path),
                    "--project-dir",
                    str(tmp_path),
                    "run",
                    "add dark mode toggle",
                ],
            )

        assert result.exit_code == 0
        assert create_subprocess.await_args.args == ("claude", "--print")
        assert create_subprocess.await_args.kwargs["stdin"] is not None
        sent_prompt = mock_proc.communicate.await_args.args[0].decode()
        assert "Task:\nadd dark mode toggle" in sent_prompt

    def test_run_can_skip_local_control_plane_when_disabled(self, runner, tmp_path):
        config_path = tmp_path / "config.yaml"
        config_path.write_text(
            textwrap.dedent(
                """\
                orchestrator:
                  planning_mode: disabled
                  evaluation_mode: disabled
                agents:
                  claude_code:
                    type: cli
                    command: claude
                    flags: ["--print"]
                    description: "Claude Code"
                    strengths: ["implementation"]
                routing:
                  rules: []
                skills: {}
                """
            )
        )

        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (b"Feature added.", b"")
        mock_proc.returncode = 0

        with (
            patch(
                "ralph.cli.main.OllamaClient",
                side_effect=AssertionError("Ollama should not be constructed"),
            ),
            patch(
                "ralph.agents.runner.asyncio.create_subprocess_exec",
                return_value=mock_proc,
            ) as create_subprocess,
        ):
            result = runner.invoke(
                cli,
                [
                    "--config",
                    str(config_path),
                    "--project-dir",
                    str(tmp_path),
                    "run",
                    "add dark mode toggle",
                ],
            )

        assert result.exit_code == 0
        assert "complete" in result.output.lower()
        prompt = create_subprocess.await_args.args[-1]
        assert "Goal: add dark mode toggle" in prompt
        assert "Task:\nadd dark mode toggle" in prompt
