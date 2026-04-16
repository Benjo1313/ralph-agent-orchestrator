"""LLM-backed task planner for decomposing user goals into task graphs."""
import json
import warnings
from typing import Any
from uuid import uuid4

from ralph.core.task_graph import Task, TaskGraph
from ralph.llm.ollama_client import Message, Role


class Planner:
    VALID_TASK_TYPES = {
        "architecture",
        "implementation",
        "test_writing",
        "code_review",
        "refactoring",
        "debugging",
    }

    def __init__(self, llm, context_budget: int) -> None:
        self.llm = llm
        self.context_budget = context_budget

    async def plan(
        self,
        goal: str,
        project_context: str | None,
        session_id: str | None = None,
        fallback_task: Task | None = None,
    ) -> TaskGraph:
        resolved_session_id = session_id or str(uuid4())

        response = await self.llm.chat(
            self._planning_messages(goal=goal, project_context=project_context),
            max_tokens=self.context_budget,
        )
        graph = self._parse_task_graph(
            response=response,
            goal=goal,
            session_id=resolved_session_id,
        )
        if graph is not None:
            return graph

        correction_response = await self.llm.chat(
            self._correction_messages(
                goal=goal,
                project_context=project_context,
                invalid_response=response,
            ),
            max_tokens=self.context_budget,
        )
        corrected_graph = self._parse_task_graph(
            response=correction_response,
            goal=goal,
            session_id=resolved_session_id,
        )
        if corrected_graph is not None:
            return corrected_graph

        warnings.warn(
            "Planner returned invalid task JSON twice; falling back to a single-task graph.",
            stacklevel=2,
        )
        return self._fallback_graph(
            goal=goal,
            session_id=resolved_session_id,
            fallback_task=fallback_task,
        )

    def _planning_messages(self, goal: str, project_context: str | None) -> list[Message]:
        system_prompt = "\n\n".join(
            [
                "You are Ralph's control-plane planner for a software development project.",
                (
                    "Produce minimal ordered subtasks that help a stronger execution agent do the "
                    "real implementation work."
                ),
                (
                    "Do not over-plan or invent deep implementation details that the coding agent "
                    "can determine while working."
                ),
                (
                    "Each task needs: id, description, task_type "
                    "(one of: architecture, implementation, test_writing, "
                    "code_review, refactoring, debugging), dependencies "
                    "(list of task ids that must complete first), and acceptance_criteria."
                ),
                "Dependencies must refer only to task ids that exist in the same response.",
                (
                    "Keep tasks actionable, sequential when needed, and scoped for CLI "
                    "execution agents."
                ),
                f"Project context:\n{project_context or 'None provided.'}",
                (
                    'Respond with ONLY valid JSON matching this schema:\n'
                    '{"tasks": [{"id": "t1", "description": "...", "task_type": "...", '
                    '"dependencies": [], "acceptance_criteria": "..."}]}'
                ),
            ]
        )
        return [
            Message(role=Role.SYSTEM, content=system_prompt),
            Message(role=Role.USER, content=goal),
        ]

    def _correction_messages(
        self,
        goal: str,
        project_context: str | None,
        invalid_response: str,
    ) -> list[Message]:
        return [
            *self._planning_messages(goal=goal, project_context=project_context),
            Message(role=Role.ASSISTANT, content=invalid_response),
            Message(
                role=Role.USER,
                content=(
                    "Your last response was invalid. Return ONLY valid JSON that exactly matches "
                    "the requested schema, includes at least one task, and uses only valid "
                    "task ids in dependencies."
                ),
            ),
        ]

    def _parse_task_graph(self, response: str, goal: str, session_id: str) -> TaskGraph | None:
        try:
            parsed = self._parse_json(response)
        except json.JSONDecodeError:
            return None

        tasks_data = parsed.get("tasks")
        if not isinstance(tasks_data, list) or not tasks_data:
            return None

        graph = TaskGraph(session_id=session_id, goal=goal)
        task_ids: set[str] = set()
        for task_data in tasks_data:
            task = self._parse_task(task_data)
            if task is None:
                return None
            if task.id in task_ids:
                return None
            task_ids.add(task.id)
            graph = graph.with_task(task)

        for task in graph.tasks.values():
            if any(dep not in graph.tasks for dep in task.dependencies):
                return None
            if task.id in task.dependencies:
                return None
        return graph

    def _parse_task(self, task_data: Any) -> Task | None:
        if not isinstance(task_data, dict):
            return None

        task_id = task_data.get("id")
        description = task_data.get("description")
        task_type = task_data.get("task_type")
        acceptance_criteria = task_data.get("acceptance_criteria")
        dependencies = task_data.get("dependencies")

        if not isinstance(task_id, str) or not task_id:
            return None
        if not isinstance(description, str) or not description:
            return None
        if not isinstance(task_type, str) or not task_type:
            return None
        if task_type not in self.VALID_TASK_TYPES:
            return None
        if not isinstance(acceptance_criteria, str) or not acceptance_criteria:
            return None
        if not isinstance(dependencies, list) or not all(
            isinstance(dep, str) for dep in dependencies
        ):
            return None

        return Task(
            id=task_id,
            description=description,
            task_type=task_type,
            dependencies=dependencies,
            acceptance_criteria=acceptance_criteria,
        )

    def _fallback_graph(self, goal: str, session_id: str, fallback_task: Task | None) -> TaskGraph:
        graph = TaskGraph(session_id=session_id, goal=goal)
        task = fallback_task or Task(id="task-0", description=goal)
        return graph.with_task(task)

    def _parse_json(self, response: str) -> dict[str, Any]:
        try:
            parsed = json.loads(response)
        except json.JSONDecodeError:
            parsed = json.loads(self._extract_json_object(response))
        if not isinstance(parsed, dict):
            raise json.JSONDecodeError("Response was not a JSON object", response, 0)
        return parsed

    def _extract_json_object(self, response: str) -> str:
        stripped = response.strip()
        if stripped.startswith("```"):
            lines = stripped.splitlines()
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            stripped = "\n".join(lines).strip()

        start = stripped.find("{")
        end = stripped.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise json.JSONDecodeError("No JSON object found", response, 0)
        return stripped[start : end + 1]
