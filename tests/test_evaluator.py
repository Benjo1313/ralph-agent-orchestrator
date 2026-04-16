"""Tests for the LLM-backed Evaluator."""
from unittest.mock import AsyncMock

import pytest

from ralph.core.evaluator import EvalDecision, Evaluator, Verdict
from ralph.core.task_graph import Task, TaskResult


@pytest.fixture
def task():
    return Task(
        id="t1",
        description="Implement dark mode",
        task_type="implementation",
        acceptance_criteria="All tests pass",
    )


class TestEvaluator:
    async def test_evaluate_pass(self, task):
        llm = AsyncMock()
        llm.chat.return_value = '{"verdict": "PASS", "reason": "Everything matches"}'
        evaluator = Evaluator(llm=llm, context_budget=321)

        decision = await evaluator.evaluate(task=task, result=TaskResult(success=True, output="ok"))

        assert decision == EvalDecision(verdict=Verdict.PASS, reason="Everything matches")

    async def test_evaluate_retry_includes_instructions(self, task):
        llm = AsyncMock()
        llm.chat.return_value = (
            '{"verdict": "RETRY", "reason": "Missing null check", '
            '"adjusted_instructions": "Add a null check before toggling"}'
        )
        evaluator = Evaluator(llm=llm, context_budget=321)

        decision = await evaluator.evaluate(
            task=task,
            result=TaskResult(success=False, error="tests failed", exit_code=1),
        )

        assert decision.verdict == Verdict.RETRY
        assert decision.adjusted_instructions == "Add a null check before toggling"

    async def test_evaluate_escalate(self, task):
        llm = AsyncMock()
        llm.chat.return_value = '{"verdict": "ESCALATE", "reason": "Merge conflict needs help"}'
        evaluator = Evaluator(llm=llm, context_budget=321)

        decision = await evaluator.evaluate(task=task, result=TaskResult(success=False))

        assert decision.verdict == Verdict.ESCALATE
        assert decision.reason == "Merge conflict needs help"

    async def test_evaluate_invalid_json_defaults_pass(self, task):
        llm = AsyncMock()
        llm.chat.side_effect = [
            "garbage",
            (
                '{"verdict": "RETRY", "reason": "Try once more", '
                '"adjusted_instructions": "Fix the failing test"}'
            ),
        ]
        evaluator = Evaluator(llm=llm, context_budget=321)

        decision = await evaluator.evaluate(task=task, result=TaskResult(success=False))

        assert decision.verdict == Verdict.RETRY
        assert llm.chat.await_count == 2

    async def test_evaluate_double_invalid_json_defaults_pass(self, task):
        llm = AsyncMock()
        llm.chat.side_effect = ["garbage", "still bad"]
        evaluator = Evaluator(llm=llm, context_budget=321)

        with pytest.warns(UserWarning, match="defaulting to PASS"):
            decision = await evaluator.evaluate(task=task, result=TaskResult(success=False))

        assert decision.verdict == Verdict.PASS

    async def test_evaluate_extracts_json_from_markdown_fence(self, task):
        llm = AsyncMock()
        llm.chat.return_value = """```json
        {"verdict": "PASS", "reason": "Looks good"}
        ```"""
        evaluator = Evaluator(llm=llm, context_budget=321)

        decision = await evaluator.evaluate(task=task, result=TaskResult(success=True))

        assert decision.verdict == Verdict.PASS
        assert decision.reason == "Looks good"

    async def test_evaluate_compresses_large_output(self, task):
        llm = AsyncMock()
        llm.chat.return_value = '{"verdict": "PASS", "reason": "ok"}'
        evaluator = Evaluator(llm=llm, context_budget=321)
        output = "\n".join(f"line {i}" for i in range(150))

        await evaluator.evaluate(task=task, result=TaskResult(success=False, output=output))

        user_message = llm.chat.await_args.args[0][1].content
        assert "... [50 lines omitted] ..." in user_message

    async def test_evaluate_respects_context_budget(self, task):
        llm = AsyncMock()
        llm.chat.return_value = '{"verdict": "PASS", "reason": "ok"}'
        evaluator = Evaluator(llm=llm, context_budget=999)

        await evaluator.evaluate(task=task, result=TaskResult(success=True))

        assert llm.chat.await_args.kwargs["max_tokens"] == 999
