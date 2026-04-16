"""Tests for the Orchestrator serial execution loop and Phase B hooks."""
from unittest.mock import AsyncMock

import pytest

from ralph.agents.runner import RunResult
from ralph.config.schema import AgentConfig, RoutingRule, SkillConfig
from ralph.core.evaluator import EvalDecision, Verdict
from ralph.core.orchestrator import Orchestrator, OrchestratorConfig
from ralph.core.task_graph import Task, TaskGraph, TaskStatus


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
def mock_runner():
    runner = AsyncMock()
    runner.run.return_value = RunResult(success=True, output="Feature implemented.", exit_code=0)
    return runner


@pytest.fixture
def api_agent_config():
    return AgentConfig(
        type="api",
        provider="openai",
        model="gpt-5.4-mini",
        description="OpenAI API",
        strengths=["implementation"],
    )


class TestOrchestratorConfig:
    def test_required_fields(self):
        cfg = OrchestratorConfig(
            model="gemma4:27b",
            endpoint="http://localhost:11434",
            context_budget={"planning": 2048, "routing": 1024, "evaluation": 2048, "retry": 1024},
        )
        assert cfg.model == "gemma4:27b"
        assert cfg.max_retries == 3

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
    def orchestrator(self, orchestrator_config, agent_config, mock_runner):
        return Orchestrator(
            config=orchestrator_config,
            agents={"claude_code": agent_config},
            routing_rules=[RoutingRule(task_type="implementation", prefer="claude_code")],
            llm=AsyncMock(),
            runner_factory=lambda cfg: mock_runner,
        )

    async def test_run_single_task_success(self, orchestrator, tmp_path):
        graph = TaskGraph(session_id="s1", goal="Add dark mode")
        graph = graph.with_task(
            Task(id="t1", description="Add dark mode toggle", agent="claude_code")
        )

        final = await orchestrator.run(graph=graph, state_dir=tmp_path / ".ralph")

        assert final.tasks["t1"].status == TaskStatus.DONE

    async def test_run_saves_state_after_each_task(self, orchestrator, tmp_path):
        graph = TaskGraph(session_id="s1", goal="Add dark mode")
        graph = graph.with_task(Task(id="t1", description="Do it", agent="claude_code"))
        state_dir = tmp_path / ".ralph"

        await orchestrator.run(graph=graph, state_dir=state_dir)

        assert (state_dir / "state.json").exists()

    async def test_run_writes_session_end_journal(self, orchestrator, tmp_path):
        graph = TaskGraph(session_id="s1", goal="Add dark mode")
        graph = graph.with_task(Task(id="t1", description="Do it", agent="claude_code"))
        state_dir = tmp_path / ".ralph"

        await orchestrator.run(graph=graph, state_dir=state_dir)

        journal_files = list((state_dir / "journal").glob("*.md"))
        assert len(journal_files) == 1
        assert "Outcome: `completed`" in journal_files[0].read_text()

    async def test_run_failed_task_marks_failed(self, orchestrator_config, agent_config, tmp_path):
        runner = AsyncMock()
        runner.run.return_value = RunResult(success=False, error="Agent crashed", exit_code=1)
        orchestrator = Orchestrator(
            config=orchestrator_config,
            agents={"claude_code": agent_config},
            routing_rules=[],
            llm=AsyncMock(),
            runner_factory=lambda cfg: runner,
        )

        graph = TaskGraph(session_id="s1", goal="Test")
        graph = graph.with_task(Task(id="t1", description="Do it", agent="claude_code"))

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

    async def test_run_blocked_dependency_stays_pending(
        self,
        orchestrator_config,
        agent_config,
        tmp_path,
    ):
        runner = AsyncMock()
        runner.run.return_value = RunResult(success=False, error="Failed", exit_code=1)
        orchestrator = Orchestrator(
            config=orchestrator_config,
            agents={"claude_code": agent_config},
            routing_rules=[],
            llm=AsyncMock(),
            runner_factory=lambda cfg: runner,
        )

        graph = TaskGraph(session_id="s1", goal="Two-step")
        t1 = Task(id="t1", description="First", agent="claude_code")
        t2 = Task(id="t2", description="Second", agent="claude_code", dependencies=["t1"])
        graph = graph.with_task(t1).with_task(t2)

        final = await orchestrator.run(graph=graph, state_dir=tmp_path / ".ralph")

        assert final.tasks["t1"].status == TaskStatus.FAILED
        assert final.tasks["t2"].status == TaskStatus.SKIPPED

    async def test_orchestrator_with_planner_injection(
        self,
        orchestrator_config,
        agent_config,
        tmp_path,
    ):
        runner = AsyncMock()
        runner.run.return_value = RunResult(success=True, output="ok", exit_code=0)
        planner = AsyncMock()
        planned_graph = TaskGraph(session_id="s1", goal="Add dark mode")
        planned_graph = planned_graph.with_task(
            Task(
                id="t1",
                description="Write tests",
                task_type="test_writing",
                agent="claude_code",
            )
        )
        planned_graph = planned_graph.with_task(
            Task(
                id="t2",
                description="Implement dark mode",
                task_type="implementation",
                agent="claude_code",
                dependencies=["t1"],
            )
        )
        planner.plan.return_value = planned_graph

        orchestrator = Orchestrator(
            config=orchestrator_config,
            agents={"claude_code": agent_config},
            routing_rules=[],
            llm=AsyncMock(),
            runner_factory=lambda cfg: runner,
            planner=planner,
        )

        initial = TaskGraph(session_id="s1", goal="Add dark mode").with_task(
            Task(id="task-0", description="Add dark mode", agent="claude_code")
        )

        final = await orchestrator.run(graph=initial, state_dir=tmp_path / ".ralph")

        planner.plan.assert_awaited_once()
        assert final.tasks["t1"].status == TaskStatus.DONE
        assert final.tasks["t2"].status == TaskStatus.DONE

    async def test_orchestrator_retries_on_retry_verdict(
        self,
        orchestrator_config,
        agent_config,
        tmp_path,
    ):
        runner = AsyncMock()
        runner.run.side_effect = [
            RunResult(success=False, error="tests failed", exit_code=1),
            RunResult(success=True, output="fixed", exit_code=0),
        ]
        evaluator = AsyncMock()
        evaluator.evaluate.side_effect = [
            EvalDecision(
                verdict=Verdict.RETRY,
                reason="Missing null check",
                adjusted_instructions="Add a null check",
            ),
            EvalDecision(verdict=Verdict.PASS, reason="Looks good"),
        ]
        orchestrator = Orchestrator(
            config=orchestrator_config,
            agents={"claude_code": agent_config},
            routing_rules=[],
            llm=AsyncMock(),
            runner_factory=lambda cfg: runner,
            evaluator=evaluator,
        )

        graph = TaskGraph(session_id="s1", goal="Fix bug").with_task(
            Task(id="t1", description="Fix bug", agent="claude_code")
        )

        final = await orchestrator.run(graph=graph, state_dir=tmp_path / ".ralph")

        assert final.tasks["t1"].status == TaskStatus.DONE
        assert final.tasks["t1"].attempt == 1
        assert final.tasks["t1"].description == "Fix bug"
        assert final.tasks["t1"].retry_guidance == "Add a null check"
        retry_prompt = runner.run.await_args_list[1].kwargs["prompt"]
        assert "Retry guidance:" in retry_prompt
        assert "Add a null check" in retry_prompt
        assert "Task:\nFix bug" in retry_prompt

    async def test_dispatch_uses_first_class_retry_guidance_field(
        self,
        orchestrator_config,
        agent_config,
        tmp_path,
    ):
        runner = AsyncMock()
        runner.run.return_value = RunResult(success=True, output="ok", exit_code=0)
        orchestrator = Orchestrator(
            config=orchestrator_config,
            agents={"claude_code": agent_config},
            routing_rules=[],
            llm=AsyncMock(),
            runner_factory=lambda cfg: runner,
        )

        graph = TaskGraph(session_id="s1", goal="Fix bug").with_task(
            Task(
                id="t1",
                description="Fix bug",
                retry_guidance="Reproduce the failure and patch the null case",
                agent="claude_code",
            )
        )

        await orchestrator.run(graph=graph, state_dir=tmp_path / ".ralph")

        prompt = runner.run.await_args.kwargs["prompt"]
        assert "Task:\nFix bug" in prompt
        assert "Retry guidance:\nReproduce the failure and patch the null case" in prompt

    async def test_orchestrator_respects_max_retries(
        self,
        agent_config,
        tmp_path,
    ):
        runner = AsyncMock()
        runner.run.side_effect = [
            RunResult(success=False, error="still broken", exit_code=1),
            RunResult(success=False, error="still broken", exit_code=1),
        ]
        evaluator = AsyncMock()
        evaluator.evaluate.side_effect = [
            EvalDecision(
                verdict=Verdict.RETRY,
                reason="Try again",
                adjusted_instructions="Try again",
            ),
            EvalDecision(
                verdict=Verdict.RETRY,
                reason="Try again",
                adjusted_instructions="Try again",
            ),
        ]
        orchestrator = Orchestrator(
            config=OrchestratorConfig(
                model="gemma4:27b",
                endpoint="http://localhost:11434",
                context_budget={"planning": 1, "routing": 1, "evaluation": 1, "retry": 1},
                max_retries=1,
            ),
            agents={"claude_code": agent_config},
            routing_rules=[],
            llm=AsyncMock(),
            runner_factory=lambda cfg: runner,
            evaluator=evaluator,
        )

        graph = TaskGraph(session_id="s1", goal="Fix bug").with_task(
            Task(id="t1", description="Fix bug", agent="claude_code")
        )

        final = await orchestrator.run(graph=graph, state_dir=tmp_path / ".ralph")

        assert final.tasks["t1"].status == TaskStatus.ESCALATED
        assert "Exceeded max retries (1)" in final.tasks["t1"].result.error

    async def test_orchestrator_escalated_skips_dependents(
        self,
        orchestrator_config,
        agent_config,
        tmp_path,
    ):
        runner = AsyncMock()
        runner.run.return_value = RunResult(success=False, error="conflict", exit_code=1)
        evaluator = AsyncMock()
        evaluator.evaluate.return_value = EvalDecision(
            verdict=Verdict.ESCALATE,
            reason="Merge conflict",
        )
        orchestrator = Orchestrator(
            config=orchestrator_config,
            agents={"claude_code": agent_config},
            routing_rules=[],
            llm=AsyncMock(),
            runner_factory=lambda cfg: runner,
            evaluator=evaluator,
        )

        graph = TaskGraph(session_id="s1", goal="Two-step")
        graph = graph.with_task(Task(id="t1", description="First", agent="claude_code"))
        graph = graph.with_task(
            Task(id="t2", description="Second", agent="claude_code", dependencies=["t1"])
        )

        final = await orchestrator.run(graph=graph, state_dir=tmp_path / ".ralph")

        assert final.tasks["t1"].status == TaskStatus.ESCALATED
        assert final.tasks["t2"].status == TaskStatus.SKIPPED

    async def test_dispatch_passes_project_context_to_runner(
        self,
        orchestrator_config,
        agent_config,
        tmp_path,
    ):
        runner = AsyncMock()
        runner.run.return_value = RunResult(success=True, output="ok", exit_code=0)
        orchestrator = Orchestrator(
            config=orchestrator_config,
            agents={"claude_code": agent_config},
            routing_rules=[],
            llm=AsyncMock(),
            runner_factory=lambda cfg: runner,
            project_context="Repo context",
        )

        graph = TaskGraph(session_id="s1", goal="Do it").with_task(
            Task(id="t1", description="Do it", agent="claude_code")
        )

        await orchestrator.run(graph=graph, state_dir=tmp_path / ".ralph")

        prompt = runner.run.await_args.kwargs["prompt"]
        assert "Project context:\nRepo context" in prompt
        assert "Task:\nDo it" in prompt
        assert runner.run.await_args.kwargs["system_message"] == "Repo context"

    async def test_dispatch_prefixes_matching_cli_skill(
        self,
        orchestrator_config,
        agent_config,
        tmp_path,
    ):
        runner = AsyncMock()
        runner.run.return_value = RunResult(success=True, output="ok", exit_code=0)
        orchestrator = Orchestrator(
            config=orchestrator_config,
            agents={"claude_code": agent_config},
            routing_rules=[],
            llm=AsyncMock(),
            runner_factory=lambda cfg: runner,
            skills={
                "tdd": SkillConfig(
                    agent="claude_code",
                    invoke="/tdd",
                    use_when=["test_writing"],
                )
            },
        )

        graph = TaskGraph(session_id="s1", goal="Write tests").with_task(
            Task(
                id="t1",
                description="Write failing tests for dark mode",
                task_type="test_writing",
                acceptance_criteria="Tests fail for the missing dark mode behavior",
                agent="claude_code",
            )
        )

        await orchestrator.run(graph=graph, state_dir=tmp_path / ".ralph")

        prompt = runner.run.await_args.kwargs["prompt"]
        assert prompt.startswith("/tdd\n\n")
        assert "Task type: test_writing" in prompt
        assert "Task:\nWrite failing tests for dark mode" in prompt
        assert "Acceptance criteria:\nTests fail for the missing dark mode behavior" in prompt

    async def test_dispatch_does_not_prefix_skill_for_different_agent(
        self,
        orchestrator_config,
        agent_config,
        api_agent_config,
        tmp_path,
    ):
        runner = AsyncMock()
        runner.run.return_value = RunResult(success=True, output="ok", exit_code=0)
        orchestrator = Orchestrator(
            config=orchestrator_config,
            agents={"codex_api": api_agent_config, "claude_code": agent_config},
            routing_rules=[],
            llm=AsyncMock(),
            runner_factory=lambda cfg: runner,
            skills={
                "tdd": SkillConfig(
                    agent="claude_code",
                    invoke="/tdd",
                    use_when=["implementation"],
                )
            },
        )

        graph = TaskGraph(session_id="s1", goal="Implement feature").with_task(
            Task(
                id="t1",
                description="Implement dark mode",
                task_type="implementation",
                agent="codex_api",
            )
        )

        await orchestrator.run(graph=graph, state_dir=tmp_path / ".ralph")

        prompt = runner.run.await_args.kwargs["prompt"]
        assert not prompt.startswith("/tdd")
        assert prompt == "Implement dark mode"

    async def test_dispatch_routes_then_applies_matching_skill(
        self,
        orchestrator_config,
        agent_config,
        tmp_path,
    ):
        runner = AsyncMock()
        runner.run.return_value = RunResult(success=True, output="ok", exit_code=0)
        orchestrator = Orchestrator(
            config=orchestrator_config,
            agents={"claude_code": agent_config},
            routing_rules=[RoutingRule(task_type="code_review", prefer="claude_code")],
            llm=AsyncMock(),
            runner_factory=lambda cfg: runner,
            skills={
                "review": SkillConfig(
                    agent="claude_code",
                    invoke="/review-pr",
                    use_when=["code_review"],
                )
            },
        )

        graph = TaskGraph(session_id="s1", goal="Review changes").with_task(
            Task(
                id="t1",
                description="Review the latest auth changes",
                task_type="code_review",
                agent=None,
            )
        )

        await orchestrator.run(graph=graph, state_dir=tmp_path / ".ralph")

        prompt = runner.run.await_args.kwargs["prompt"]
        assert prompt.startswith("/review-pr\n\n")
        assert "Task type: code_review" in prompt
        assert "Task:\nReview the latest auth changes" in prompt

    async def test_dispatch_builds_cli_prompt_envelope_with_dependencies_and_attempt(
        self,
        orchestrator_config,
        agent_config,
        tmp_path,
    ):
        runner = AsyncMock()
        runner.run.return_value = RunResult(success=True, output="ok", exit_code=0)
        orchestrator = Orchestrator(
            config=orchestrator_config,
            agents={"claude_code": agent_config},
            routing_rules=[],
            llm=AsyncMock(),
            runner_factory=lambda cfg: runner,
            project_context="Shared repo context",
        )

        graph = TaskGraph(session_id="s1", goal="Ship feature")
        graph = graph.with_task(Task(id="t1", description="Write tests", agent="claude_code"))
        graph = graph.with_task(
            Task(
                id="t2",
                description="Implement feature",
                task_type="implementation",
                agent="claude_code",
                dependencies=["t1"],
                acceptance_criteria="Tests pass and feature works",
                attempt=1,
            )
        )

        await orchestrator.run(graph=graph, state_dir=tmp_path / ".ralph")

        prompt = runner.run.await_args_list[1].kwargs["prompt"]
        assert "Ralph execution envelope" in prompt
        assert "Goal: Ship feature" in prompt
        assert "Task ID: t2" in prompt
        assert "Attempt: 2" in prompt
        assert "Dependencies: t1" in prompt
        assert "Project context:\nShared repo context" in prompt

    async def test_run_writes_checkpoint_journals_for_numeric_interval(
        self,
        agent_config,
        tmp_path,
    ):
        runner = AsyncMock()
        runner.run.return_value = RunResult(success=True, output="ok", exit_code=0)
        orchestrator = Orchestrator(
            config=OrchestratorConfig(
                model="gemma4:27b",
                endpoint="http://localhost:11434",
                context_budget={"planning": 1, "routing": 1, "evaluation": 1, "retry": 1},
                journal_interval=1,
            ),
            agents={"claude_code": agent_config},
            routing_rules=[],
            llm=AsyncMock(),
            runner_factory=lambda cfg: runner,
        )

        graph = TaskGraph(session_id="s1", goal="Two-step")
        graph = graph.with_task(Task(id="t1", description="First", agent="claude_code"))
        graph = graph.with_task(Task(id="t2", description="Second", agent="claude_code"))

        await orchestrator.run(graph=graph, state_dir=tmp_path / ".ralph")

        journal_files = list((tmp_path / ".ralph" / "journal").glob("*.md"))
        assert len(journal_files) == 3
        checkpoint_files = [path for path in journal_files if "checkpoint_" in path.name]
        assert len(checkpoint_files) == 2
