# Ralph — Local LLM Multi-Agent Development Orchestrator

Python CLI tool that uses a local LLM (Gemma 4 27B via Ollama) to orchestrate AI coding agents (Claude Code, Codex, direct API calls) in a stateful, self-correcting development loop.

## Tech Stack

- **Python 3.12+**
- **Click** — CLI framework
- **Pydantic** — config and data model validation
- **PyYAML** — config parsing
- **Ollama** — local LLM hosting (Gemma 4 27B)
- **Anthropic SDK** — direct Claude API calls
- **OpenAI SDK** — direct GPT API calls
- **pytest + pytest-asyncio** — testing
- **Ruff** — linting and formatting

## Project Structure

```
ralph/
├── cli/                  — CLI entry point, argument parsing
│   └── main.py
├── core/
│   ├── orchestrator.py   — Main loop logic
│   ├── planner.py        — Task decomposition (Gemma interaction)
│   ├── router.py         — Agent + skill selection
│   ├── evaluator.py      — Result assessment
│   ├── task_graph.py     — Task data structures and state management
│   ├── llm.py            — Ollama client wrapper
│   ├── context.py        — Context scoping for agents and orchestrator
│   ├── response_parser.py — JSON response extraction and validation
│   └── prompts/          — Prompt template files (.txt)
├── agents/
│   ├── base.py           — Agent interface (execute → result)
│   ├── cli_agent.py      — CLI subprocess wrapper (Claude Code, Codex)
│   ├── api_agent.py      — Direct API wrapper (Anthropic, OpenAI)
│   └── registry.py       — Agent loading and lookup
├── skills/
│   └── registry.py       — Skill loading and invocation
├── memory/
│   ├── state.py          — State file read/write (.ralph/state.json)
│   ├── journal.py        — Journal entry generation and retrieval
│   └── resume.py         — Resume prompt construction
├── config/
│   ├── loader.py         — YAML config loading and merging
│   └── schema.py         — Pydantic config models
└── tests/
```

## Build & Test

```bash
# Install in development mode
pip install -e ".[dev]"

# Run tests
pytest

# Lint
ruff check ralph/ tests/
ruff format ralph/ tests/
```

## Configuration

Two-tier YAML config:
- **Global:** `~/.ralph/config.yaml` — orchestrator settings, agent definitions, routing rules, skills
- **Per-project:** `.ralph/project.yaml` — project name, conventions, test/build commands, routing overrides

See `config.yaml.example` for the full annotated global config.

API keys via environment variables: `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`.

## Key Conventions

- **All I/O is async** — `asyncio` throughout, agents run as async subprocess/API calls
- **Pydantic everywhere** — config, task graph, agent results all validated with Pydantic models
- **No global state** — everything flows through constructor injection
- **Test isolation** — all external dependencies (Ollama, subprocess, APIs) mocked via dependency injection
- **Atomic state writes** — write to temp file, rename; never corrupt state on crash

## Design Docs

- `docs/ralph-orchestrator-design.md` — full spec
- `docs/ralph-mvp-implementation-plan.md` — Phase A implementation plan
