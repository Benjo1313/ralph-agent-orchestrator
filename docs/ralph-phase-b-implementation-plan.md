# Phase B Implementation Plan: Ralph Intelligence Layer

**Spec:** `docs/ralph-orchestrator-design.md`
**Scope:** Phase B — API dispatch, LLM planning, result evaluation, retry loop
**Depends on:** Phase A (complete — 108 tests, all passing)

---

## Requirements Restatement

Phase A built the execution skeleton: config, CLI, task graph, state, agent dispatch (CLI), and a serial task loop. But right now Ralph is a dumb passthrough — `ralph run "add dark mode"` creates a single task and dispatches it to an agent verbatim. Phase B adds the **intelligence**:

1. **API agent dispatch** — Wire Anthropic and OpenAI SDK calls into the existing `_run_api` stub
2. **LLM-driven task planning** — Gemma decomposes a goal into a multi-task graph with types, dependencies, and acceptance criteria
3. **Result evaluation** — Gemma assesses each task result and decides pass/retry/escalate
4. **Retry loop** — Failed tasks get retried with adjusted instructions, up to `max_retries`

These four features complete the **plan → route → dispatch → evaluate → retry/advance** loop described in the design spec.

## Implementation Order

API dispatch first (lowest risk, pure SDK wiring), then planning (changes how graphs are built), then evaluation + retry (changes how results are handled). Each phase builds on the previous and can be shipped independently.

---

## Phase B1: API Agent Dispatch

**Goal:** `_run_api` calls real SDKs instead of returning "not yet supported."

**Scope:** `ralph/agents/runner.py` only. No new files.

### Design Decisions

- **Environment variables for API keys:** `ANTHROPIC_API_KEY` and `OPENAI_API_KEY` — read at call time, not at config load time. Missing key → `RunResult(success=False, error="...")`.
- **No streaming:** Both SDK calls use non-streaming `.create()`. Streaming adds complexity with no benefit for batch orchestration.
- **Response extraction:** Anthropic → `response.content[0].text`. OpenAI → `response.choices[0].message.content`.
- **Error handling:** SDK exceptions → `RunResult(success=False, error=str(e))`. Same pattern as CLI's `FileNotFoundError` handling.
- **System message:** Include `orchestrator_context` from project config if available. This means `_run_api` needs the prompt only — the caller is responsible for prepending skill invoke strings (already handled in `_dispatch`).

### Changes

| File | Change |
|------|--------|
| `ralph/agents/runner.py` | Replace `_run_api` stub with Anthropic + OpenAI SDK calls |

### Tests (write first)

| Test | What it verifies |
|------|-----------------|
| `test_run_api_anthropic_success` | Mocked `anthropic.AsyncAnthropic().messages.create` → success |
| `test_run_api_openai_success` | Mocked `openai.AsyncOpenAI().chat.completions.create` → success |
| `test_run_api_anthropic_missing_key` | No `ANTHROPIC_API_KEY` → graceful failure |
| `test_run_api_openai_missing_key` | No `OPENAI_API_KEY` → graceful failure |
| `test_run_api_anthropic_sdk_error` | SDK raises → `RunResult(success=False)` |
| `test_run_api_openai_sdk_error` | SDK raises → `RunResult(success=False)` |
| `test_run_api_unknown_provider` | provider="azure" → meaningful error message |

**Estimated complexity:** Low. Straightforward SDK wiring with mocked tests.

---

## Phase B2: LLM-Driven Task Planning (Planner)

**Goal:** Gemma decomposes a user goal into a structured `TaskGraph` with typed, ordered subtasks.

**New file:** `ralph/core/planner.py`

### Design Decisions

**Gemma output schema (JSON):**
```json
{
  "tasks": [
    {
      "id": "t1",
      "description": "Write failing tests for dark mode toggle",
      "task_type": "test_writing",
      "dependencies": [],
      "acceptance_criteria": "Tests exist and fail when run"
    },
    {
      "id": "t2",
      "description": "Implement dark mode toggle in SettingsView",
      "task_type": "implementation",
      "dependencies": ["t1"],
      "acceptance_criteria": "All tests pass, toggle visible in settings"
    }
  ]
}
```

- **`task_type` field on Task:** Currently `Task` has no `task_type`. Add it as `str | None = None`. The Router already matches on `task_type` strings — the planner provides them, closing the loop.
- **Prompt template:** System prompt with project context + conventions + available agents/skills → user prompt with the goal. Gemma responds with JSON. The `context_budget["planning"]` cap applies.
- **Structured output parsing:** `json.loads()` on Gemma's response. If parsing fails or schema doesn't match, retry the LLM call once with a correction prompt. If that fails too, fall back to a single-task graph (current behavior) and log a warning.
- **No new dependencies:** Uses existing `OllamaClient.chat()`.
- **Planner is a standalone class** — `Planner(llm: OllamaClient, context_budget: int)` with `async def plan(goal: str, project_context: str | None) -> TaskGraph`. Orchestrator calls it.
- **Orchestrator change:** Instead of building a single-task graph in `cli/main.py`, the orchestrator's `run()` method (or a new `plan_and_run()`) calls the planner first. The CLI still builds a fallback single-task graph and passes it — the orchestrator uses the planner to expand it.

### Changes

| File | Change |
|------|--------|
| `ralph/core/planner.py` | **New.** `Planner` class with prompt template and JSON parsing |
| `ralph/core/task_graph.py` | Add `task_type: str \| None = None` to `Task` |
| `ralph/core/orchestrator.py` | Accept optional `Planner`, call it before the task loop |
| `ralph/cli/main.py` | Wire planner into orchestrator construction |
| `tests/test_planner.py` | **New.** Planner tests |
| `tests/test_task_graph.py` | Test `task_type` field on `Task` |
| `tests/test_orchestrator.py` | Test orchestrator with planner injection |

### Prompt Template (draft)

```
System: You are a task planner for a software development project. Decompose the user's goal into ordered subtasks.

Each task needs: id, description, task_type (one of: architecture, implementation, test_writing, code_review, refactoring, debugging), dependencies (list of task ids that must complete first), and acceptance_criteria.

Project context:
{project_context}

Respond with ONLY valid JSON matching this schema:
{"tasks": [{"id": "t1", "description": "...", "task_type": "...", "dependencies": [], "acceptance_criteria": "..."}]}

User: {goal}
```

### Tests (write first)

| Test | What it verifies |
|------|-----------------|
| `test_plan_parses_valid_json` | Mocked LLM returns valid JSON → correct TaskGraph |
| `test_plan_sets_task_types` | Each task has a `task_type` from the plan |
| `test_plan_preserves_dependencies` | Dependency IDs are wired correctly |
| `test_plan_invalid_json_retries` | First call returns garbage → correction prompt → parses second attempt |
| `test_plan_double_failure_falls_back` | Both attempts fail → single-task fallback graph |
| `test_plan_empty_tasks_falls_back` | `{"tasks": []}` → fallback |
| `test_plan_includes_project_context` | Project conventions appear in the prompt |
| `test_plan_respects_context_budget` | `max_tokens` passed to LLM matches config |

**Estimated complexity:** Medium. Prompt engineering + JSON parsing + retry logic + orchestrator integration.

---

## Phase B3: Result Evaluation + Retry Loop

**Goal:** After each task, Gemma evaluates the result and decides: **PASS**, **RETRY** (with new instructions), or **ESCALATE** (ask the human).

**New file:** `ralph/core/evaluator.py`

### Design Decisions

**Gemma evaluation output schema:**
```json
{
  "verdict": "PASS",
  "reason": "All tests pass, implementation matches acceptance criteria"
}
```
or
```json
{
  "verdict": "RETRY",
  "reason": "Tests fail — missing null check in toggle handler",
  "adjusted_instructions": "Add null check for userPreferences before toggling dark mode"
}
```
or
```json
{
  "verdict": "ESCALATE",
  "reason": "Merge conflict in settings.swift — needs human resolution"
}
```

- **Evaluator class:** `Evaluator(llm: OllamaClient, context_budget: int)` with `async def evaluate(task: Task, result: TaskResult) -> EvalDecision`.
- **`EvalDecision` dataclass:** `verdict: Verdict` (enum: PASS/RETRY/ESCALATE), `reason: str`, `adjusted_instructions: str | None`.
- **Retry mechanics in Orchestrator:** On RETRY, increment `task.attempt`, update description with adjusted instructions, reset status to PENDING, re-queue. On ESCALATE, mark FAILED with escalation reason. On PASS, mark DONE (current behavior).
- **`max_retries` enforcement:** If `task.attempt >= config.max_retries`, auto-escalate regardless of evaluator verdict.
- **New `TaskStatus` value:** Add `ESCALATED` to distinguish "evaluator said stop" from "agent crashed." Update `is_terminal` to include it.
- **Evaluation prompt uses compressed result:** Not the full agent output. For CLI agents: exit code + first/last 50 lines of stdout + stderr. This respects `context_budget["evaluation"]`.
- **Fallback on parse failure:** If Gemma's evaluation response isn't valid JSON, treat as PASS (optimistic) and log a warning. We don't want evaluation parsing bugs to block the loop.

### Changes

| File | Change |
|------|--------|
| `ralph/core/evaluator.py` | **New.** `Evaluator`, `EvalDecision`, `Verdict` enum |
| `ralph/core/task_graph.py` | Add `ESCALATED` to `TaskStatus`, update `is_terminal` |
| `ralph/core/orchestrator.py` | Integrate evaluator into the task loop, add retry logic |
| `ralph/cli/main.py` | Wire evaluator, handle ESCALATED status in output |
| `tests/test_evaluator.py` | **New.** Evaluator tests |
| `tests/test_task_graph.py` | Test `ESCALATED` status |
| `tests/test_orchestrator.py` | Test retry loop, max_retries, escalation |
| `tests/test_run_integration.py` | Integration test with evaluation in the loop |

### Tests (write first)

| Test | What it verifies |
|------|-----------------|
| `test_evaluate_pass` | Mocked LLM returns PASS → `EvalDecision(verdict=PASS)` |
| `test_evaluate_retry_includes_instructions` | RETRY → adjusted_instructions populated |
| `test_evaluate_escalate` | ESCALATE → verdict + reason |
| `test_evaluate_invalid_json_defaults_pass` | Garbage response → optimistic PASS |
| `test_orchestrator_retries_on_retry_verdict` | Task gets re-queued with incremented attempt |
| `test_orchestrator_respects_max_retries` | After N retries → ESCALATED regardless |
| `test_orchestrator_escalated_skips_dependents` | ESCALATED task → dependents SKIPPED |
| `test_orchestrator_retry_uses_adjusted_instructions` | Retry prompt includes evaluator's instructions |

**Estimated complexity:** Medium-high. Touches the core loop, adds a new decision point, changes task lifecycle.

---

## Implementation Order & Dependencies

```
B1: API Dispatch ─────────────── (independent, can ship alone)

B2: Planner ──────────────────── (adds task_type to Task, changes graph construction)
        │
        ▼
B3: Evaluator + Retry ────────── (depends on B2's task_type for evaluation context)
```

B1 is fully independent. B2 and B3 are logically sequential — the evaluator needs `task_type` and `acceptance_criteria` from the planner to make good decisions.

## Risks

| Risk | Severity | Mitigation |
|------|----------|------------|
| Gemma JSON output is unreliable | HIGH | Retry with correction prompt + single-task fallback. Strict schema validation before accepting. |
| Evaluation parse failures block the loop | MEDIUM | Optimistic PASS fallback on parse failure. Evaluation is advisory, not authoritative. |
| Prompt templates need tuning against real Gemma | MEDIUM | All LLM calls are mocked in tests. Real prompt tuning happens after functional correctness is proven. |
| `task_type` addition is a schema change | LOW | `str \| None = None` is backward compatible. Existing state files deserialize fine. |
| API key handling edge cases | LOW | Explicit check before SDK call. Test all paths. |

## CLAUDE.md Updates Required

After implementation:
- Update test count
- Add `planner.py`, `evaluator.py` to project structure
- Add `ESCALATED` to TaskStatus documentation
- Document the planning and evaluation prompt contracts
- Move planner/evaluator from "Not yet built" to "Built"
