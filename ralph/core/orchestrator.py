"""Orchestrator: serial task execution loop."""
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from ralph.agents.runner import AgentRunner, RunResult
from ralph.config.schema import AgentConfig, RoutingRule
from ralph.core.router import Router
from ralph.core.task_graph import Task, TaskGraph, TaskResult, TaskStatus
from ralph.memory.state import StateManager


@dataclass
class OrchestratorConfig:
    model: str
    endpoint: str
    context_budget: dict[str, int]
    max_retries: int = 3


class Orchestrator:
    def __init__(
        self,
        config: OrchestratorConfig,
        agents: dict[str, AgentConfig],
        routing_rules: list[RoutingRule],
        llm,
        runner_factory: Callable[[AgentConfig], AgentRunner],
    ) -> None:
        self.config = config
        self.agents = agents
        self.router = Router(agents=agents, rules=routing_rules)
        self.llm = llm
        self.runner_factory = runner_factory

    async def run(self, graph: TaskGraph, state_dir: Path) -> TaskGraph:
        state_manager = StateManager(state_dir=state_dir)

        while not graph.is_complete:
            ready = graph.ready_tasks()
            if not ready:
                # Deadlock: unfinished tasks but none are ready — skip blocked ones
                graph = self._skip_blocked(graph)
                break

            # Serial execution: take the first ready task
            task = ready[0]
            graph = graph.with_task(task.model_copy(update={"status": TaskStatus.IN_PROGRESS}))

            result = await self._dispatch(task)

            if result.success:
                new_status = TaskStatus.DONE
            else:
                new_status = TaskStatus.FAILED

            task_result = TaskResult(
                success=result.success,
                output=result.output,
                error=result.error,
            )
            graph = graph.with_task(
                task.model_copy(update={"status": new_status, "result": task_result})
            )

            state_manager.save(graph)

            # If a task failed, skip its dependents
            if not result.success:
                graph = self._skip_dependents(graph, task.id)

        return graph

    async def _dispatch(self, task: Task) -> RunResult:
        agent_name = task.agent
        if agent_name is None or agent_name not in self.agents:
            # Route by task type derived from description (MVP: use agent name or fallback)
            try:
                decision = self.router.route(task_type=task.description)
                agent_name = decision.agent_name
            except ValueError as e:
                return RunResult(success=False, error=str(e))

        agent_config = self.agents[agent_name]
        runner = self.runner_factory(agent_config)
        return await runner.run(prompt=task.description)

    def _skip_dependents(self, graph: TaskGraph, failed_id: str) -> TaskGraph:
        for task in graph.tasks.values():
            if failed_id in task.dependencies and not task.is_terminal:
                graph = graph.with_task(task.model_copy(update={"status": TaskStatus.SKIPPED}))
                # Recursively skip dependents of the newly skipped task
                graph = self._skip_dependents(graph, task.id)
        return graph

    def _skip_blocked(self, graph: TaskGraph) -> TaskGraph:
        for task in graph.tasks.values():
            if not task.is_terminal:
                graph = graph.with_task(task.model_copy(update={"status": TaskStatus.SKIPPED}))
        return graph
