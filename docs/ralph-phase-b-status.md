# Phase B Status

Date: 2026-04-06
Status: Complete

## Summary

Phase B from `docs/ralph-phase-b-implementation-plan.md` has been implemented:

1. B1: API agent dispatch
2. B2: LLM-driven task planning
3. B3: Result evaluation and retry loop

Ralph now supports the full serial loop:

`plan -> route -> dispatch -> evaluate -> retry or advance`

## Completed Work

### B1: API agent dispatch

Implemented in `ralph/agents/runner.py`.

Behavior:
- Anthropic calls use `AsyncAnthropic().messages.create(...)`
- OpenAI calls use `AsyncOpenAI().chat.completions.create(...)`
- API keys are read from `ANTHROPIC_API_KEY` and `OPENAI_API_KEY`
- missing keys return graceful `RunResult(success=False, error=...)`
- SDK exceptions return graceful failures
- unsupported providers return a clear error

### B2: Planner

Implemented in `ralph/core/planner.py` and integrated into `ralph/core/orchestrator.py` and `ralph/cli/main.py`.

Behavior:
- Gemma decomposes the user goal into a structured `TaskGraph`
- tasks now include `task_type` and `acceptance_criteria`
- planning uses project context plus available agents and skills
- invalid planner JSON gets one correction retry
- double failure falls back to a single-task graph

### B3: Evaluator and retry loop

Implemented in `ralph/core/evaluator.py`, `ralph/core/orchestrator.py`, and `ralph/core/task_graph.py`.

Behavior:
- Gemma returns `PASS`, `RETRY`, or `ESCALATE`
- retry updates the task description with adjusted instructions
- retries increment `task.attempt`
- `max_retries` is enforced in the orchestrator
- escalation uses `TaskStatus.ESCALATED`
- dependents of failed or escalated tasks are skipped
- invalid evaluator JSON defaults to `PASS`

## Validation

Validation completed with:

```bash
python -m pytest -q -p no:cacheprovider
python -m ruff check ralph tests
```

Result:
- 133 tests passed
- Ruff passed

## Files Added

- `ralph/core/planner.py`
- `ralph/core/evaluator.py`
- `tests/test_planner.py`
- `tests/test_evaluator.py`
- `tests/conftest.py`

## Files Updated

- `ralph/agents/runner.py`
- `ralph/cli/main.py`
- `ralph/core/orchestrator.py`
- `ralph/core/task_graph.py`
- `ralph/llm/ollama_client.py`
- `tests/test_agent_runner.py`
- `tests/test_orchestrator.py`
- `tests/test_run_integration.py`
- `tests/test_task_graph.py`
- `CLAUDE.md`

## Remaining Work After Phase B

Not part of Phase B and still pending:
- `--resume` orchestration support
- journal / narrative log
- parallel task execution

## Notes

- `docs/ralph-orchestrator-design.md` still has a stale rollout table that labels Phase B as parallelism.
- `docs/ralph-phase-b-implementation-plan.md` is the authoritative Phase B plan.
- In this sandbox, pytest temp and cache paths need workspace-local handling, which is why tests run with `-p no:cacheprovider` and use `tests/conftest.py`.

---

## Phase B Replan Progress

Date: 2026-04-15
Status: Replan items B4-B8 implemented

This section tracks the post-implementation Phase B replan in `docs/ralph-phase-b-replan.md`.

### Implemented Under The Replan

#### B4: Skill-aware CLI dispatch

Behavior:
- CLI dispatch resolves skills from configured `use_when` task types
- matching skill invokes are prepended before the CLI execution envelope
- non-matching agents fall back to the normal prompt path

#### B5: Durable resume

Behavior:
- `ralph run --resume` continues saved state from `.ralph/state.json`
- new runs are blocked when an in-progress session exists unless `--resume` or `--fresh` is chosen
- complete saved sessions are treated as no-op resumes

#### B6: Journal and session narrative

Behavior:
- Ralph writes markdown journal entries under `.ralph/journal/`
- `journal_interval` supports `session_end` or periodic checkpoint entries
- journals are human-readable and separate from machine state

#### B7: CLI adapter hardening

Behavior:
- CLI prompt delivery supports `argument` and `stdin`
- CLI prompts now use a compact execution envelope with goal, task metadata, dependencies, acceptance criteria, and project context
- subprocess failures surface richer stdout/stderr and exit-code details
- CLI/API config validation is stricter

#### B8: Prompt and context tightening for Ralph-controlled decisions

Behavior:
- planner and evaluator prompts frame Ralph as a control plane around stronger execution agents
- planner/evaluator both attempt one schema-repair pass and extract JSON from fenced/noisy output
- retry guidance is rendered as a separate prompt section
- local planning and evaluation can now be disabled independently with `planning_mode` / `evaluation_mode`
- when both modes are disabled, Ralph still routes, dispatches, journals, resumes, and persists state without requiring Ollama

### Additional concern reduction completed alongside the replan

Behavior:
- retry state now lives on `Task.retry_guidance` instead of being encoded into `task.description`
- backward compatibility remains for older saved state containing embedded retry guidance

### Current validation snapshots

Recent targeted validation completed with:

```bash
python -m pytest tests/test_config.py tests/test_cli.py tests/test_run_integration.py tests/test_orchestrator.py -q -p no:cacheprovider
python -m ruff check ralph/config/schema.py ralph/cli/main.py ralph/core/orchestrator.py tests/test_config.py tests/test_cli.py tests/test_run_integration.py
```

Result:
- 71 targeted tests passed
- Ruff passed on touched code
