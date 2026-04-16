"""Tests for the LLM-backed Planner."""
from unittest.mock import AsyncMock

import pytest

from ralph.core.planner import Planner
from ralph.core.task_graph import Task


@pytest.fixture
def planner_llm():
    llm = AsyncMock()
    llm.chat.return_value = """{
      "tasks": [
        {
          "id": "t1",
          "description": "Write failing tests",
          "task_type": "test_writing",
          "dependencies": [],
          "acceptance_criteria": "Tests fail"
        },
        {
          "id": "t2",
          "description": "Implement feature",
          "task_type": "implementation",
          "dependencies": ["t1"],
          "acceptance_criteria": "Tests pass"
        }
      ]
    }"""
    return llm


class TestPlanner:
    async def test_plan_parses_valid_json(self, planner_llm):
        planner = Planner(llm=planner_llm, context_budget=1234)

        graph = await planner.plan(goal="Add dark mode", project_context="SwiftUI app")

        assert set(graph.tasks) == {"t1", "t2"}
        assert graph.tasks["t1"].description == "Write failing tests"
        assert graph.tasks["t2"].acceptance_criteria == "Tests pass"

    async def test_plan_sets_task_types(self, planner_llm):
        planner = Planner(llm=planner_llm, context_budget=1234)

        graph = await planner.plan(goal="Add dark mode", project_context=None)

        assert graph.tasks["t1"].task_type == "test_writing"
        assert graph.tasks["t2"].task_type == "implementation"

    async def test_plan_preserves_dependencies(self, planner_llm):
        planner = Planner(llm=planner_llm, context_budget=1234)

        graph = await planner.plan(goal="Add dark mode", project_context=None)

        assert graph.tasks["t2"].dependencies == ["t1"]

    async def test_plan_invalid_json_retries(self):
        llm = AsyncMock()
        llm.chat.side_effect = [
            "not json",
            """{
              "tasks": [
                {
                  "id": "t1",
                  "description": "Do the work",
                  "task_type": "implementation",
                  "dependencies": [],
                  "acceptance_criteria": "Done"
                }
              ]
            }""",
        ]
        planner = Planner(llm=llm, context_budget=222)

        graph = await planner.plan(goal="Do the work", project_context="Repo context")

        assert set(graph.tasks) == {"t1"}
        assert llm.chat.await_count == 2
        correction_messages = llm.chat.await_args_list[1].args[0]
        assert correction_messages[-1].content.startswith("Your last response was invalid")

    async def test_plan_extracts_json_from_markdown_fence(self):
        llm = AsyncMock()
        llm.chat.return_value = """```json
        {
          "tasks": [
            {
              "id": "t1",
              "description": "Do the work",
              "task_type": "implementation",
              "dependencies": [],
              "acceptance_criteria": "Done"
            }
          ]
        }
        ```"""
        planner = Planner(llm=llm, context_budget=123)

        graph = await planner.plan(goal="Do the work", project_context=None)

        assert set(graph.tasks) == {"t1"}

    async def test_plan_invalid_dependency_retries(self):
        llm = AsyncMock()
        llm.chat.side_effect = [
            """{
              "tasks": [
                {
                  "id": "t1",
                  "description": "Implement feature",
                  "task_type": "implementation",
                  "dependencies": ["missing"],
                  "acceptance_criteria": "Done"
                }
              ]
            }""",
            """{
              "tasks": [
                {
                  "id": "t1",
                  "description": "Implement feature",
                  "task_type": "implementation",
                  "dependencies": [],
                  "acceptance_criteria": "Done"
                }
              ]
            }""",
        ]
        planner = Planner(llm=llm, context_budget=123)

        graph = await planner.plan(goal="Do the work", project_context=None)

        assert set(graph.tasks) == {"t1"}
        assert llm.chat.await_count == 2

    async def test_plan_double_failure_falls_back(self):
        llm = AsyncMock()
        llm.chat.side_effect = ["not json", "still bad"]
        planner = Planner(llm=llm, context_budget=333)
        fallback_task = Task(id="task-0", description="Add dark mode", agent="claude_code")

        with pytest.warns(UserWarning, match="falling back"):
            graph = await planner.plan(
                goal="Add dark mode",
                project_context=None,
                session_id="session-1",
                fallback_task=fallback_task,
            )

        assert graph.session_id == "session-1"
        assert graph.tasks["task-0"].agent == "claude_code"

    async def test_plan_empty_tasks_falls_back(self):
        llm = AsyncMock()
        llm.chat.side_effect = ['{"tasks": []}', '{"tasks": []}']
        planner = Planner(llm=llm, context_budget=444)

        with pytest.warns(UserWarning, match="falling back"):
            graph = await planner.plan(goal="Add dark mode", project_context=None)

        assert len(graph.tasks) == 1
        only_task = next(iter(graph.tasks.values()))
        assert only_task.description == "Add dark mode"

    async def test_plan_includes_project_context(self, planner_llm):
        planner = Planner(llm=planner_llm, context_budget=555)

        await planner.plan(
            goal="Add dark mode",
            project_context="This repo uses TDD and pytest.",
        )

        messages = planner_llm.chat.await_args.args[0]
        assert "This repo uses TDD and pytest." in messages[0].content
        assert "control-plane planner" in messages[0].content.lower()
        assert "minimal ordered subtasks" in messages[0].content.lower()

    async def test_plan_respects_context_budget(self, planner_llm):
        planner = Planner(llm=planner_llm, context_budget=777)

        await planner.plan(goal="Add dark mode", project_context=None)

        assert planner_llm.chat.await_args.kwargs["max_tokens"] == 777
