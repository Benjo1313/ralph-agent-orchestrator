# Ralph — Local LLM Multi-Agent Development Orchestrator

Python CLI tool that uses a local LLM (Gemma 4 27B via Ollama) to orchestrate AI coding agents (Claude Code, Codex, direct API calls) in a stateful, self-correcting development loop.

## Tech Stack

- **Python 3.12+**
- **Click** — CLI framework
- **Pydantic v2** — config validation and immutable data models (`frozen=True`)
- **PyYAML** — config parsing
- **Ollama** (Python SDK) — async local LLM client
- **pytest + pytest-asyncio** — testing
- **Ruff** — linting and formatting

## Project Structure

```
ralph/
├── ralph/
│   ├── cli/
│   │   └── main.py              — Click CLI: `ralph run`, `ralph config *`
│   ├── core/
│   │   ├── orchestrator.py      — Serial task execution loop; dispatches tasks, saves state
│   │   ├── router.py            — Maps task types to agents via ordered routing rules
│   │   └── task_graph.py        — Task, TaskGraph, TaskStatus, TaskResult — all immutable Pydantic models
│   ├── agents/
│   │   └── runner.py            — AgentRunner: CLI subprocess dispatch + API dispatch (stub)
│   ├── llm/
│   │   └── ollama_client.py     — Async Ollama wrapper (OllamaClient, Message, Role, OllamaError)
│   ├── skills/
│   │   └── registry.py          — SkillRegistry: skill lookup by name or use-case
│   ├── memory/
│   │   └── state.py             — StateManager: save/load TaskGraph as JSON to .ralph/state.json
│   └── config/
│       ├── schema.py            — Pydantic models: RalphConfig, AgentConfig, RoutingRule, SkillConfig, etc.
│       └── loader.py            — Two-tier YAML config loading and merging (global + per-project)
├── tests/
│   ├── test_cli.py              — CLI command tests (Click CliRunner)
│   ├── test_config.py           — Config loading, schema validation, two-tier merge
│   ├── test_task_graph.py       — Task, TaskGraph, TaskStatus immutability and graph logic
│   ├── test_state_manager.py    — StateManager save/load/clear
│   ├── test_ollama_client.py    — OllamaClient (mocked ollama SDK)
│   ├── test_agent_runner.py     — AgentRunner CLI subprocess and API dispatch
│   ├── test_router.py           — Router rule matching, fallback, missing-agent skip
│   ├── test_skill_registry.py   — SkillRegistry get/skills_for/list_all
│   ├── test_orchestrator.py     — Orchestrator task loop, dependency handling, state persistence
│   └── test_run_integration.py  — End-to-end `ralph run` via CliRunner + mocked subprocess
├── docs/
│   ├── ralph-orchestrator-design.md       — Full architecture spec
│   └── ralph-mvp-implementation-plan.md   — Phase A implementation plan
├── config.yaml.example          — Annotated global config template
├── pyproject.toml
└── README.md                    — User-facing docs with setup, config, and usage guide
```

**108 tests across 10 files, all passing.** Run `pytest` before every commit.

## Build & Test

```bash
# Install in development mode
pip install -e ".[dev]"

# Run all tests
pytest

# Run a specific test file
pytest tests/test_orchestrator.py -v

# Lint and format
ruff check ralph/ tests/
ruff format ralph/ tests/
```

## Configuration

Two-tier YAML config merged at runtime:
- **Global:** `~/.ralph/config.yaml` — orchestrator settings, agent definitions, routing rules, skills
- **Per-project:** `.ralph/project.yaml` — project name, conventions, test/build commands, routing overrides

Merge behavior: project `routing_overrides` are **appended** after global routing rules (not replaced). Everything else is additive.

See `config.yaml.example` for the full annotated global config. Generate starters with:
```bash
ralph config init            # creates ~/.ralph/config.yaml
ralph config init-project    # creates .ralph/project.yaml in current dir
```

API keys from environment variables: `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`.

## Key Architectural Conventions

### Immutable Pydantic models (`frozen=True`)
`Task` and `TaskGraph` are frozen Pydantic models — never mutate them. Always use `model_copy(update={...})` to produce a new instance. `TaskGraph.with_task(task)` is the canonical way to add or update a task in the graph.

```python
# Correct — returns new graph
graph = graph.with_task(task.model_copy(update={"status": TaskStatus.DONE}))

# Wrong — will raise FrozenInstanceError
task.status = TaskStatus.DONE
```

### `runner_factory` injection pattern
`Orchestrator` does not create `AgentRunner` instances directly. It accepts a `runner_factory: Callable[[AgentConfig], AgentRunner]` argument. Tests pass a lambda that returns a mock runner without needing to patch internals. The CLI wires the real factory: `runner_factory=lambda agent_cfg: AgentRunner(agent_config=agent_cfg)`.

### Async boundary at the CLI
The entire orchestration loop is `async`. Click commands are synchronous. `asyncio.run()` is the explicit boundary at the end of each `@cli.command`. Do NOT use `async def` for Click command handlers — this breaks pytest integration (CliRunner-based tests must call synchronous functions).

### Dependency injection throughout
No global state. Every external dependency (Ollama, subprocess, APIs) is injected via constructor parameters and can be replaced with mocks in tests. `OllamaClient` is passed into `Orchestrator`; `AgentRunner` is passed in via the factory.

### Task routing
`Router` matches tasks by `task_type` against ordered `RoutingRule` entries. First match wins. Rules whose `prefer` agent isn't in the agents dict are silently skipped. Falls back to the first configured agent if nothing matches. Tasks with an explicit `agent` field set in `Task` bypass routing entirely.

### State persistence
`StateManager` saves the full `TaskGraph` as JSON after every task completes. The JSON is written via `model_dump_json()` and loaded back via `TaskGraph.model_validate_json()`. `StateError` is raised on missing file, corrupt JSON, or schema mismatch. Never edit `state.json` by hand.

### CLI agent dispatch
CLI agents: `[command] + flags + [prompt]` passed to `asyncio.create_subprocess_exec`. Non-zero exit code → `RunResult(success=False)`. API agent dispatch is stubbed (returns `success=False` with a "not yet supported" error).

## What's Built vs Planned

**Built (Phase A — MVP):**
- Config loading and validation (two-tier YAML, Pydantic schemas)
- CLI: `ralph run`, `ralph run --dry-run`, `ralph run --fresh`, `ralph config show/validate/init/init-project`
- Task graph: immutable `Task`/`TaskGraph`, dependency tracking, ready-task selection, skip-on-failure
- State persistence: save/load/clear `state.json`
- Ollama client: async `chat()` wrapper
- Agent runner: CLI subprocess dispatch; API stub
- Router: config-driven ordered rule matching with fallback
- Skill registry: lookup by name and use-case
- Orchestrator: serial task loop with dependency-aware scheduling and state writes after each task

**Not yet built (future phases):**
- LLM-driven task planning (Gemma decomposing the user's goal into subtasks)
- Result evaluation (Gemma assessing agent output and deciding retry/pass)
- `--resume` flag (wired in CLI, not yet implemented in the loop)
- API agent dispatch (Anthropic, OpenAI SDKs — infrastructure ready, SDK calls stubbed)
- Journal / narrative log
- Parallel task execution

## Design Docs

- `docs/ralph-orchestrator-design.md` — full architecture spec
- `docs/ralph-mvp-implementation-plan.md` — Phase A plan
