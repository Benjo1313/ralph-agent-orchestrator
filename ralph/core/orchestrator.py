"""Orchestrator: serial task execution loop with planning and evaluation hooks."""
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from ralph.agents.runner import AgentRunner, RunResult
from ralph.config.schema import AgentConfig, RoutingRule, SkillConfig
from ralph.core.evaluator import EvalDecision, Evaluator, Verdict
from ralph.core.planner import Planner
from ralph.core.router import Router
from ralph.core.task_graph import Task, TaskGraph, TaskResult, TaskStatus
from ralph.memory.journal import JournalWriter
from ralph.memory.state import StateManager
from ralph.skills.registry import SkillRegistry


@dataclass
class OrchestratorConfig:
    model: str | None
    endpoint: str | None
    context_budget: dict[str, int]
    max_retries: int = 3
    journal_interval: str | int = "session_end"


class Orchestrator:
    def __init__(
        self,
        config: OrchestratorConfig,
        agents: dict[str, AgentConfig],
        routing_rules: list[RoutingRule],
        llm,
        runner_factory: Callable[[AgentConfig], AgentRunner],
        planner: Planner | None = None,
        evaluator: Evaluator | None = None,
        project_context: str | None = None,
        skills: dict[str, SkillConfig] | None = None,
    ) -> None:
        self.config = config
        self.agents = agents
        self.router = Router(agents=agents, rules=routing_rules)
        self.skill_registry = SkillRegistry(agents=agents, skills=skills or {})
        self.llm = llm
        self.runner_factory = runner_factory
        self.planner = planner
        self.evaluator = evaluator
        self.project_context = project_context
        self._current_goal: str | None = None

    async def run(self, graph: TaskGraph, state_dir: Path) -> TaskGraph:
        self._current_goal = graph.goal
        state_manager = StateManager(state_dir=state_dir)
        journal_writer = JournalWriter(state_dir=state_dir)
        initial_graph = graph
        written_checkpoints: set[int] = set()

        if self.planner is not None and self._should_plan(graph):
            fallback_task = next(iter(graph.tasks.values()), None)
            graph = await self.planner.plan(
                goal=graph.goal,
                project_context=self.project_context,
                session_id=graph.session_id,
                fallback_task=fallback_task,
            )
            self._current_goal = graph.goal

        while not graph.is_complete:
            ready = graph.ready_tasks()
            if not ready:
                graph = self._skip_blocked(graph)
                state_manager.save(graph)
                self._maybe_write_checkpoint(
                    journal_writer=journal_writer,
                    initial_graph=initial_graph,
                    graph=graph,
                    written_checkpoints=written_checkpoints,
                )
                break

            task = ready[0]
            graph = graph.with_task(task.model_copy(update={"status": TaskStatus.IN_PROGRESS}))

            result = await self._dispatch(task)
            task_result = TaskResult(
                success=result.success,
                output=result.output,
                error=result.error,
                exit_code=result.exit_code,
            )

            if self.evaluator is None:
                graph = self._apply_dispatch_result(graph=graph, task=task, result=task_result)
            else:
                decision = await self.evaluator.evaluate(task=task, result=task_result)
                graph = self._apply_evaluation(
                    graph=graph,
                    task=task,
                    result=task_result,
                    decision=decision,
                )

            state_manager.save(graph)
            self._maybe_write_checkpoint(
                journal_writer=journal_writer,
                initial_graph=initial_graph,
                graph=graph,
                written_checkpoints=written_checkpoints,
            )

        journal_writer.write(initial_graph=initial_graph, final_graph=graph)
        return graph

    async def _dispatch(self, task: Task) -> RunResult:
        agent_name = task.agent
        if agent_name is None or agent_name not in self.agents:
            try:
                decision = self.router.route(task_type=task.task_type or task.description)
                agent_name = decision.agent_name
            except ValueError as e:
                return RunResult(success=False, error=str(e))

        agent_config = self.agents[agent_name]
        runner = self.runner_factory(agent_config)
        prompt = self._build_prompt(task=task, agent_name=agent_name, agent_config=agent_config)
        return await runner.run(prompt=prompt, system_message=self.project_context)

    def _build_prompt(self, task: Task, agent_name: str, agent_config: AgentConfig) -> str:
        skill = self._resolve_skill(task=task, agent_name=agent_name, agent_config=agent_config)
        if agent_config.type != "cli":
            if skill is None:
                return task.description
            return f"{skill.invoke} {task.description}"

        return self._build_cli_prompt(task=task, skill_invoke=skill.invoke if skill else None)

    def _build_cli_prompt(self, task: Task, skill_invoke: str | None) -> str:
        task_body, retry_guidance = self._task_body_and_retry_guidance(task)
        lines: list[str] = []
        if skill_invoke is not None:
            lines.append(skill_invoke)
            lines.append("")

        lines.extend(
            [
                "Ralph execution envelope",
                "Operate non-interactively in the current repository.",
                (
                    "Complete the task if you can. If you are blocked, explain the concrete "
                    "blocker and the next best action instead of asking for clarification."
                ),
                "Return a concise summary of changes made, tests run, and any remaining risks.",
                "",
                f"Goal: {self._current_goal or task.description}",
                f"Task ID: {task.id}",
                f"Attempt: {task.attempt + 1}",
            ]
        )

        if task.task_type:
            lines.append(f"Task type: {task.task_type}")
        if task.dependencies:
            lines.append(f"Dependencies: {', '.join(task.dependencies)}")

        if task.acceptance_criteria:
            lines.extend(["", "Acceptance criteria:", task.acceptance_criteria])

        if self.project_context:
            lines.extend(["", "Project context:", self.project_context])

        lines.extend(["", "Task:", task_body])
        if retry_guidance:
            lines.extend(["", "Retry guidance:", retry_guidance])
        return "\n".join(lines)

    def _resolve_skill(self, task: Task, agent_name: str, agent_config: AgentConfig):
        if agent_config.type != "cli" or task.task_type is None:
            return None

        for skill in self.skill_registry.skills_for(task.task_type):
            if skill.agent_config == agent_config and skill.skill.agent == agent_name:
                return skill

        return None

    def _should_plan(self, graph: TaskGraph) -> bool:
        if not graph.tasks:
            return True
        if len(graph.tasks) != 1:
            return False
        task = next(iter(graph.tasks.values()))
        return (
            task.description == graph.goal
            and task.dependencies == []
            and task.result is None
            and task.status == TaskStatus.PENDING
        )

    def _apply_dispatch_result(self, graph: TaskGraph, task: Task, result: TaskResult) -> TaskGraph:
        new_status = TaskStatus.DONE if result.success else TaskStatus.FAILED
        graph = graph.with_task(task.model_copy(update={"status": new_status, "result": result}))
        if new_status == TaskStatus.FAILED:
            graph = self._skip_dependents(graph, task.id)
        return graph

    def _apply_evaluation(
        self,
        graph: TaskGraph,
        task: Task,
        result: TaskResult,
        decision: EvalDecision,
    ) -> TaskGraph:
        if decision.verdict == Verdict.PASS:
            return graph.with_task(
                task.model_copy(update={"status": TaskStatus.DONE, "result": result})
            )

        if decision.verdict == Verdict.RETRY:
            if task.attempt >= self.config.max_retries:
                escalated_reason = (
                    f"Exceeded max retries ({self.config.max_retries}). {decision.reason}"
                )
                graph = graph.with_task(
                    task.model_copy(
                        update={
                            "status": TaskStatus.ESCALATED,
                            "result": result.model_copy(update={"error": escalated_reason}),
                        }
                    )
                )
                return self._skip_dependents(graph, task.id)

            retry_instructions = decision.adjusted_instructions or decision.reason
            return graph.with_task(
                task.model_copy(
                    update={
                        "status": TaskStatus.PENDING,
                        "retry_guidance": retry_instructions,
                        "result": None,
                        "attempt": task.attempt + 1,
                    }
                )
            )

        graph = graph.with_task(
            task.model_copy(
                update={
                    "status": TaskStatus.ESCALATED,
                    "result": result.model_copy(update={"error": decision.reason}),
                }
            )
        )
        return self._skip_dependents(graph, task.id)

    def _task_body_and_retry_guidance(self, task: Task) -> tuple[str, str | None]:
        if task.retry_guidance:
            return task.description, task.retry_guidance
        return self._split_retry_guidance(task.description)

    def _split_retry_guidance(self, description: str) -> tuple[str, str | None]:
        marker = "\n\nRetry guidance:\n"
        if marker not in description:
            return description, None

        task_body, retry_guidance = description.split(marker, maxsplit=1)
        cleaned_guidance = retry_guidance.strip() or None
        return task_body, cleaned_guidance

    def _skip_dependents(self, graph: TaskGraph, failed_id: str) -> TaskGraph:
        for task in graph.tasks.values():
            if failed_id in task.dependencies and not task.is_terminal:
                graph = graph.with_task(task.model_copy(update={"status": TaskStatus.SKIPPED}))
                graph = self._skip_dependents(graph, task.id)
        return graph

    def _skip_blocked(self, graph: TaskGraph) -> TaskGraph:
        for task in graph.tasks.values():
            if not task.is_terminal:
                graph = graph.with_task(task.model_copy(update={"status": TaskStatus.SKIPPED}))
        return graph

    def _maybe_write_checkpoint(
        self,
        journal_writer: JournalWriter,
        initial_graph: TaskGraph,
        graph: TaskGraph,
        written_checkpoints: set[int],
    ) -> None:
        if not isinstance(self.config.journal_interval, int):
            return

        terminal_count = sum(1 for task in graph.tasks.values() if task.is_terminal)
        interval = self.config.journal_interval
        if terminal_count == 0 or terminal_count % interval != 0:
            return
        if terminal_count in written_checkpoints:
            return

        journal_writer.write(
            initial_graph=initial_graph,
            final_graph=graph,
            trigger=f"checkpoint_{terminal_count}",
        )
        written_checkpoints.add(terminal_count)
