# Ralph - Local LLM Multi-Agent Development Orchestrator

Python CLI tool that orchestrates AI coding agents in a stateful, self-correcting development loop. A local Gemma/Ollama model remains available for optional control-plane planning and evaluation.

Default product posture:
- local-first orchestration
- CLI-first execution
- API agents supported, but optional

## Tech Stack

- Python 3.12+
- Click
- Pydantic v2
- PyYAML
- Ollama Python SDK
- Anthropic SDK
- OpenAI SDK
- pytest + pytest-asyncio
- Ruff

## Project Structure

```text
ralph/
|-- ralph/
|   |-- cli/
|   |   `-- main.py
|   |-- core/
|   |   |-- orchestrator.py
|   |   |-- planner.py
|   |   |-- evaluator.py
|   |   |-- router.py
|   |   `-- task_graph.py
|   |-- agents/
|   |   `-- runner.py
|   |-- llm/
|   |   `-- ollama_client.py
|   |-- skills/
|   |   `-- registry.py
|   |-- memory/
|   |   `-- state.py
|   `-- config/
|       |-- schema.py
|       `-- loader.py
|-- tests/
|   |-- conftest.py
|   |-- test_cli.py
|   |-- test_config.py
|   |-- test_task_graph.py
|   |-- test_state_manager.py
|   |-- test_ollama_client.py
|   |-- test_agent_runner.py
|   |-- test_router.py
|   |-- test_skill_registry.py
|   |-- test_planner.py
|   |-- test_evaluator.py
|   |-- test_orchestrator.py
|   `-- test_run_integration.py
|-- docs/
|   |-- ralph-orchestrator-design.md
|   |-- ralph-mvp-implementation-plan.md
|   |-- ralph-phase-b-implementation-plan.md
|   |-- ralph-concerns.md
|   |-- ralph-future-features.md
|   |-- ralph-phase-b-replan.md
|   `-- ralph-phase-b-status.md
|-- config.yaml.example
|-- pyproject.toml
|-- README.md
`-- CLAUDE.md
```

133 tests across 12 files are passing.

## Build And Test

```bash
# Install in development mode
python -m pip install -e ".[dev]"

# Run all tests
python -m pytest -q -p no:cacheprovider

# Run a specific test file
python -m pytest tests/test_orchestrator.py -v -p no:cacheprovider

# Lint
python -m ruff check ralph tests
python -m ruff format ralph tests
```

Notes:
- In this sandbox, `pytest` temp and cache paths need to stay inside the workspace. Use `-p no:cacheprovider`.
- `tests/conftest.py` overrides `tmp_path` to a repo-local temp directory for the same reason.

## Configuration

Two-tier YAML config merged at runtime:
- Global: `~/.ralph/config.yaml`
- Per-project: `.ralph/project.yaml`

Merge behavior:
- Project `routing_overrides` are appended after global routing rules.
- Everything else is additive.

API keys come from environment variables if API agents are used:
- `ANTHROPIC_API_KEY`
- `OPENAI_API_KEY`

## Key Architectural Conventions

### Immutable models
`Task` and `TaskGraph` are frozen Pydantic models. Never mutate them directly. Use `model_copy(update={...})` and `TaskGraph.with_task(...)`.

### Runner injection
`Orchestrator` accepts `runner_factory: Callable[[AgentConfig], AgentRunner]`. Tests inject mock runners; the CLI wires the real `AgentRunner`.

### Async boundary
The orchestration loop is async, but Click handlers stay synchronous. The CLI uses `asyncio.run()` at the boundary.

### Dependency injection
External boundaries are injected instead of being global:
- Ollama client
- agent runners
- planner
- evaluator

### Optional control-plane model
`OrchestratorConfig` now supports:
- `planning_mode: "local" | "disabled"`
- `evaluation_mode: "local" | "disabled"`

When both are `disabled`, the CLI must not instantiate `OllamaClient`, `Planner`, or `Evaluator`. Ralph should still route, dispatch, resume, persist state, and journal correctly in that mode.

### Task routing
`Router` matches `task_type` against ordered `RoutingRule` entries. First match wins. Missing preferred agents are skipped. If nothing matches, Ralph falls back to the first configured agent. Explicit `task.agent` bypasses routing.

### Planning contract
`Planner` asks Gemma for strict JSON with:
- `id`
- `description`
- `task_type`
- `dependencies`
- `acceptance_criteria`

If parsing or schema validation fails, Ralph retries once with a correction prompt. If that also fails, it falls back to a single-task graph.
Planner also strips fenced/noisy output down to the JSON object before giving up, and rejects invalid task types, duplicate ids, self-dependencies, and references to missing tasks.

### Evaluation contract
`Evaluator` asks Gemma for strict JSON with:
- `verdict`
- `reason`
- optional `adjusted_instructions`

Allowed verdicts:
- `PASS`
- `RETRY`
- `ESCALATE`

If evaluation JSON is invalid, Ralph asks once for corrected JSON. If that also fails, it defaults optimistically to `PASS` so evaluator formatting errors do not block the loop.

### Task lifecycle
`Task` now carries:
- `task_type`
- `acceptance_criteria`
- `attempt`

`TaskStatus` includes:
- `PENDING`
- `IN_PROGRESS`
- `DONE`
- `FAILED`
- `ESCALATED`
- `SKIPPED`

`ESCALATED` is terminal and means Ralph stopped automatically and needs human input. Dependents of failed or escalated tasks are marked `SKIPPED`.

### State persistence
`StateManager` saves the full `TaskGraph` as JSON after each task update. Never edit `state.json` by hand.

### Agent dispatch
CLI agents:
- supports `prompt_mode: argument` and `prompt_mode: stdin`
- CLI dispatch builds a compact execution envelope with task metadata and project context
- non-zero exit codes return `RunResult(success=False, exit_code=...)` with surfaced stdout/stderr details
- this is the primary execution path Ralph should optimize for

API agents:
- Anthropic via `AsyncAnthropic().messages.create(...)`
- OpenAI via `AsyncOpenAI().chat.completions.create(...)`
- API keys are read at call time
- missing keys or SDK errors return `RunResult(success=False, error=...)`
- these are optional integrations and should not be assumed in the baseline user setup

### Skills
`SkillRegistry` exists and skills are included in planner context.

Current behavior:
- CLI dispatch prepends the configured skill invoke string when `task.task_type` matches `SkillConfig.use_when` and the chosen agent matches `SkillConfig.agent`
- if no skill matches, Ralph still sends the structured CLI execution envelope
- API agents remain optional and do not depend on skill-prefixed dispatch

## Built Status

Built through Phase B:
- config loading and validation
- CLI commands
- immutable task graph and state persistence
- Ollama chat wrapper
- CLI and API agent dispatch
- routing by task type
- planner-driven task decomposition
- evaluator-driven pass/retry/escalate decisions
- retry loop with `max_retries`
- escalation state handling
- `--resume` state recovery in the orchestration loop
- human-readable session journaling under `.ralph/journal/`
- CLI adapter hardening with structured prompt envelopes, stdin support, and stricter agent validation
- B8 prompt/context tightening with stronger planner/evaluator prompts, schema repair, and cleaner retry guidance rendering
- optional local planning/evaluation modes so CLI-first runs do not require Ollama
- integration and unit coverage for the full loop

Current direction after Phase B:
- keep the intelligence loop as-is
- prioritize CLI-first usability
- treat API agents as optional, not baseline
- prioritize prompt/context tightening for Ralph-controlled decisions

Still not built:
- parallel task execution

## Docs

- `docs/ralph-orchestrator-design.md`
- `docs/ralph-mvp-implementation-plan.md`
- `docs/ralph-phase-b-implementation-plan.md`
- `docs/ralph-concerns.md`
- `docs/ralph-future-features.md`
- `docs/ralph-phase-b-replan.md`
- `docs/ralph-phase-b-status.md`

## Known Doc Drift

- Historical implementation authority for shipped Phase B work:
  `docs/ralph-phase-b-implementation-plan.md`
- Current direction authority for post-implementation priorities:
  `docs/ralph-phase-b-replan.md`
