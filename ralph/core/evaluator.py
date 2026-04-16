"""LLM-backed result evaluator for Ralph's retry and escalation loop."""
import json
import warnings
from dataclasses import dataclass
from enum import StrEnum

from ralph.core.task_graph import Task, TaskResult
from ralph.llm.ollama_client import Message, Role


class Verdict(StrEnum):
    PASS = "PASS"
    RETRY = "RETRY"
    ESCALATE = "ESCALATE"


@dataclass(frozen=True)
class EvalDecision:
    verdict: Verdict
    reason: str
    adjusted_instructions: str | None = None


class Evaluator:
    def __init__(self, llm, context_budget: int) -> None:
        self.llm = llm
        self.context_budget = context_budget

    async def evaluate(self, task: Task, result: TaskResult) -> EvalDecision:
        response = await self.llm.chat(
            self._evaluation_messages(task=task, result=result),
            max_tokens=self.context_budget,
        )

        try:
            return self._parse_decision(response)
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            correction_response = await self.llm.chat(
                self._correction_messages(task=task, result=result, invalid_response=response),
                max_tokens=self.context_budget,
            )
            try:
                return self._parse_decision(correction_response)
            except (json.JSONDecodeError, KeyError, TypeError, ValueError) as correction_exc:
                detail = f"{exc}; correction failed: {correction_exc}"
            else:  # pragma: no cover - explicit for readability
                detail = str(exc)
            warnings.warn(
                f"Evaluator returned invalid JSON; defaulting to PASS. Details: {detail}",
                stacklevel=2,
            )
            return EvalDecision(
                verdict=Verdict.PASS,
                reason="Evaluation parsing failed; defaulting to PASS.",
            )

    def _evaluation_messages(self, task: Task, result: TaskResult) -> list[Message]:
        system_prompt = "\n\n".join(
            [
                "You are Ralph's control-plane evaluator for a software task result.",
                (
                    "Decide whether the task should PASS, RETRY, or ESCALATE based on the task, "
                    "acceptance criteria, and concrete execution outcome."
                ),
                (
                    "Do not re-plan the whole project or ask for more information unless "
                    "escalation is required."
                ),
                "PASS when the task appears complete enough to move forward.",
                "RETRY when there is a concrete next step Ralph can send back to the same agent.",
                "ESCALATE only when human input or intervention is genuinely required.",
                (
                    'Return ONLY valid JSON with keys: verdict, reason, and optional '
                    '"adjusted_instructions" for RETRY verdicts.'
                ),
                (
                    'If verdict is RETRY, "adjusted_instructions" should be short, concrete, '
                    "and directly actionable by the execution agent."
                ),
            ]
        )
        task_details = "\n".join(
            [
                f"Task ID: {task.id}",
                f"Description: {task.description}",
                f"Task Type: {task.task_type or 'unknown'}",
                f"Acceptance Criteria: {task.acceptance_criteria or 'not provided'}",
                f"Attempt: {task.attempt}",
                "",
                "Result summary:",
                self._compress_result(result),
            ]
        )
        return [
            Message(role=Role.SYSTEM, content=system_prompt),
            Message(role=Role.USER, content=task_details),
        ]

    def _correction_messages(
        self,
        task: Task,
        result: TaskResult,
        invalid_response: str,
    ) -> list[Message]:
        return [
            *self._evaluation_messages(task=task, result=result),
            Message(role=Role.ASSISTANT, content=invalid_response),
            Message(
                role=Role.USER,
                content=(
                    "Your last response was invalid. Return ONLY valid JSON with verdict, reason, "
                    'and optional adjusted_instructions. Do not include markdown fences or prose.'
                ),
            ),
        ]

    def _compress_result(self, result: TaskResult) -> str:
        sections = [f"Success: {result.success}"]
        if result.exit_code is not None:
            sections.append(f"Exit code: {result.exit_code}")
        if result.output:
            sections.append(f"Output:\n{self._compress_text(result.output)}")
        if result.error:
            sections.append(f"Error:\n{self._compress_text(result.error)}")
        return "\n\n".join(sections)

    def _compress_text(self, text: str) -> str:
        lines = text.splitlines()
        if len(lines) <= 100:
            if len(text) <= 4000:
                return text
            return f"{text[:2000]}\n... [truncated {len(text) - 4000} chars] ...\n{text[-2000:]}"

        head = lines[:50]
        tail = lines[-50:]
        omitted = len(lines) - 100
        return "\n".join(
            [
                *head,
                f"... [{omitted} lines omitted] ...",
                *tail,
            ]
        )

    def _parse_decision(self, response: str) -> EvalDecision:
        payload = self._parse_json(response)
        verdict = Verdict(str(payload["verdict"]).upper())
        reason = payload["reason"]
        adjusted_instructions = payload.get("adjusted_instructions")
        if not isinstance(reason, str) or not reason:
            raise ValueError("reason must be a non-empty string")
        if adjusted_instructions is not None and not isinstance(adjusted_instructions, str):
            raise ValueError("adjusted_instructions must be a string when present")
        return EvalDecision(
            verdict=verdict,
            reason=reason,
            adjusted_instructions=adjusted_instructions,
        )

    def _parse_json(self, response: str) -> dict:
        try:
            payload = json.loads(response)
        except json.JSONDecodeError:
            payload = json.loads(self._extract_json_object(response))
        if not isinstance(payload, dict):
            raise json.JSONDecodeError("Response was not a JSON object", response, 0)
        return payload

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
