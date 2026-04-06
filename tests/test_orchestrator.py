"""Tests for the Orchestrator — serial task loop."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from ralph.core.orchestrator import Orchestrator, OrchestratorConfig
from ralph.core.task_graph import Task, TaskGraph, TaskStatus
from ralph.agents.runner import RunResult
from ralph.config.schema import AgentConfig, RoutingRule


@pytest.fixture
def agent_config():
    return AgentConfig(
        type="cli",
        command="claude",
        flags=["--print"],
        description="Claude Code",
        strengths=["implementation"],
    )


@pytest.fixture
def orchestrator_config():
    return OrchestratorConfig(
        model="gemma4:27b",
        endpoint="http://localhost:11434",
        context_budget={"planning": 2048, "routing": 1024, "evaluation": 2048, "retry": 1024},
    )


@pytest.fixture
def mock_llm():
    """Returns an async mock that simulates OllamaClient.chat."""
    llm = AsyncMock()
    llm.chat.return_value = "task_type: implementation"
    return llm


@pytest.fixture
def mock_runner():
    runner = AsyncMock()
    runner.run.return_value = RunResult(success=True, output="Feature implemented.")
    return runner


class TestOrchestratorConfig:
    def test_required_fields(self):
        cfg = OrchestratorConfig(
            model="gemma4:27b",
            endpoint="http://localhost:11434",
            context_budget={"planning": 2048, "routing": 1024, "evaluation": 2048, "retry": 1024},
        )
        assert cfg.model == "gemma4:27b"
        assert cfg.max_retries == 3  # default

    def test_custom_max_retries(self):
        cfg = OrchestratorConfig(
            model="x",
            endpoint="http://localhost",
            context_budget={},
            max_retries=5,
        )
        assert cfg.max_retries == 5


class TestOrchestrator:
    @pytest.fixture
    def orchestrator(self, orchestrator_config, agent_config, mock_llm, mock_runner):
        return Orchestrator(
            config=orchestrator_config,
            agents={"claude_code": agent_config},
            routing_rules=[RoutingRule(task_type="implementation", prefer="claude_code")],
            llm=mock_llm,
            runner_factory=lambda cfg: mock_runner,
        )

    async def test_run_single_task_success(self, orchestrator, tmp_path):
        graph = TaskGraph(session_id="s1", goal="Add dark mode")
        task = Task(id="t1", description="Add dark mode toggle", agent="claude_code")
        graph = graph.with_task(task)

        final = await orchestrator.run(graph=graph, state_dir=tmp_path / ".ralph")

        assert final.tasks["t1"].status == TaskStatus.DONE

    async def test_run_saves_state_after_each_task(self, orchestrator, tmp_path):
        graph = TaskGraph(session_id="s1", goal="Add dark mode")
        task = Task(id="t1", description="Do it", agent="claude_code")
        graph = graph.with_task(task)
        state_dir = tmp_path / ".ralph"

        await orchestrator.run(graph=graph, state_dir=state_dir)

        assert (state_dir / "state.json").exists()

    async def test_run_failed_task_marks_failed(self, orchestrator_config, agent_config, tmp_path):
        mock_llm = AsyncMock()
        mock_llm.chat.return_value = "task_type: implementation"
        mock_runner = AsyncMock()
        mock_runner.run.return_value = RunResult(success=False, error="Agent crashed")

        orchestrator = Orchestrator(
            config=orchestrator_config,
            agents={"claude_code": agent_config},
            routing_rules=[],
            llm=mock_llm,
            runner_factory=lambda cfg: mock_runner,
        )

        graph = TaskGraph(session_id="s1", goal="Test")
        task = Task(id="t1", description="Do it", agent="claude_code")
        graph = graph.with_task(task)

        final = await orchestrator.run(graph=graph, state_dir=tmp_path / ".ralph")

        assert final.tasks["t1"].status == TaskStatus.FAILED
        assert final.tasks["t1"].result.error == "Agent crashed"

    async def test_run_respects_task_order_with_dependencies(self, orchestrator, tmp_path):
        graph = TaskGraph(session_id="s1", goal="Two-step task")
        t1 = Task(id="t1", description="Write tests", agent="claude_code")
        t2 = Task(id="t2", description="Implement", agent="claude_code", dependencies=["t1"])
        graph = graph.with_task(t1).with_task(t2)

        final = await orchestrator.run(graph=graph, state_dir=tmp_path / ".ralph")

        assert final.tasks["t1"].status == TaskStatus.DONE
        assert final.tasks["t2"].status == TaskStatus.DONE

    async def test_run_empty_graph_is_noop(self, orchestrator, tmp_path):
        graph = TaskGraph(session_id="s1", goal="Nothing to do")
        final = await orchestrator.run(graph=graph, state_dir=tmp_path / ".ralph")
        assert final.is_complete

    async def test_run_blocked_dependency_stays_pending(self, orchestrator_config, agent_config, tmp_path):
        """If t1 fails, t2 (which depends on t1) should be skipped, not stuck."""
        mock_llm = AsyncMock()
        mock_runner = AsyncMock()
        mock_runner.run.return_value = RunResult(success=False, error="Failed")

        orchestrator = Orchestrator(
            config=orchestrator_config,
            agents={"claude_code": agent_config},
            routing_rules=[],
            llm=mock_llm,
            runner_factory=lambda cfg: mock_runner,
        )

        graph = TaskGraph(session_id="s1", goal="Two-step")
        t1 = Task(id="t1", description="First", agent="claude_code")
        t2 = Task(id="t2", description="Second", agent="claude_code", dependencies=["t1"])
        graph = graph.with_task(t1).with_task(t2)

        final = await orchestrator.run(graph=graph, state_dir=tmp_path / ".ralph")

        assert final.tasks["t1"].status == TaskStatus.FAILED
        assert final.tasks["t2"].status == TaskStatus.SKIPPED
