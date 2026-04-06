# Ralph

Ralph is a local LLM orchestrator for AI-assisted software development. It sits between you and your coding agents (Claude Code, Codex, or direct API calls), using a local Gemma model to plan work, route tasks to the right agent, and run a self-correcting execution loop — all from your terminal.

You describe a task. Ralph figures out how to do it, picks the right agent, runs it, checks the result, and handles retries. You only get pulled in when something genuinely needs a human decision.

---

## Table of Contents

- [How It Works](#how-it-works)
- [Prerequisites](#prerequisites)
- [Installation](#installation)
- [Configuration](#configuration)
  - [Global config](#global-config-ralphconfigyaml)
  - [Per-project config](#per-project-config-ralphprojectyaml)
  - [API keys](#api-keys)
- [Usage](#usage)
- [Agents: CLI vs API](#agents-cli-vs-api)
  - [CLI agents](#cli-agents-claude-code-codex)
  - [API agents](#api-agents-anthropic-openai)
- [Routing Rules](#routing-rules)
- [Skills](#skills)
- [State and Resuming](#state-and-resuming)
- [Project Structure](#project-structure)
- [Development](#development)

---

## How It Works

```
You type:  ralph run "add a dark mode toggle to the settings screen"

Ralph:
  1. Loads your global config (~/.ralph/config.yaml) and
     your project config (.ralph/project.yaml)

  2. Builds a task graph — a single task for MVP, multiple
     subtasks once LLM planning is wired in

  3. For each task, picks the best agent using your routing rules

  4. Dispatches the task to the agent:
       - CLI agents (Claude Code, Codex): spawns a subprocess,
         passes the task as a prompt, captures stdout
       - API agents (Claude, GPT): calls the provider SDK directly

  5. Persists the result to .ralph/state.json

  6. Reports success or failure, exits nonzero on any failed task
```

**Ralph does not touch your code directly.** It delegates all code changes to your configured agents. Ralph's local Gemma model handles orchestration decisions (planning, routing, evaluation) — not implementation. This keeps the local model doing what a small model does well (structured decisions), and your cloud agents doing what they do well (understanding and writing code).

### What runs where

| Component | Where it runs |
|-----------|--------------|
| Ralph CLI | Your local machine |
| Gemma 4 27B (orchestrator) | Ollama on your GPU machine (can be remote) |
| Claude Code / Codex (agents) | Your local machine (subprocess) |
| Claude API / OpenAI API | Anthropic / OpenAI cloud |

---

## Prerequisites

**Required:**

- Python 3.12+
- [Ollama](https://ollama.com) running with your orchestrator model pulled
- At least one configured agent (Claude Code CLI, Codex CLI, or an API key)

**For CLI agents:**

- [Claude Code](https://docs.anthropic.com/en/docs/claude-code) — `npm install -g @anthropic-ai/claude-code`
- [Codex](https://github.com/openai/codex) — `npm install -g @openai/codex`

**For API agents:**

- `ANTHROPIC_API_KEY` environment variable (for Claude API)
- `OPENAI_API_KEY` environment variable (for OpenAI/GPT)

**Setting up Ollama:**

```bash
# Install Ollama: https://ollama.com/download

# Pull the recommended orchestrator model
ollama pull gemma4:27b

# Verify it works
ollama run gemma4:27b "Say hello"
```

If your GPU machine is separate from your dev machine, Ollama can run there and expose its API over the network. Set `endpoint` in your config to point at it (e.g., `http://192.168.1.50:11434`).

---

## Installation

```bash
# Clone the repo
git clone <repo-url>
cd ralph

# Create a virtual environment
python3 -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# Install Ralph and its dependencies
pip install -e .

# Verify it installed correctly
ralph --version
```

---

## Configuration

Ralph uses a two-tier config system: a global config for your machine-wide settings (which agents you have, your Ollama endpoint, routing preferences) and a per-project config for project-specific context and overrides.

### Global config: `~/.ralph/config.yaml`

Generate a starter config:

```bash
ralph config init
```

This creates `~/.ralph/config.yaml` from the bundled example. Edit it to match your setup.

**Full annotated example:**

```yaml
orchestrator:
  model: gemma4:27b          # The Ollama model name (must be pulled: ollama pull gemma4:27b)
  provider: ollama
  endpoint: http://localhost:11434  # Ollama server URL — change if running on another machine
  context_budget:
    planning: 4096     # Max tokens sent to Gemma for task decomposition
    routing: 2048      # Max tokens for agent selection decisions
    evaluation: 3072   # Max tokens for result assessment
    retry: 2048        # Max tokens for retry instructions
  re_anchor_interval: 5   # Re-state the original goal to Gemma every N tasks
  max_retries: 3          # Retries before escalating to you
  journal_interval: session_end  # When to write a narrative log ("session_end" or a number)

agents:
  # CLI agents: Ralph spawns a subprocess and passes the task as a prompt argument.
  # The agent must be installed and on your PATH.
  claude_code:
    type: cli
    command: claude              # The command to run
    flags: ["--print"]           # Extra flags always passed before the prompt
    description: "Full-featured coding agent with git awareness and tool use"
    strengths: ["architecture", "complex_logic", "refactoring", "debugging"]

  codex:
    type: cli
    command: codex
    description: "Fast implementation agent"
    strengths: ["straightforward_implementation", "boilerplate"]

  # API agents: Ralph calls the provider SDK directly, no subprocess.
  # API keys come from environment variables (see API Keys section below).
  claude_api:
    type: api
    provider: anthropic          # "anthropic" or "openai"
    model: claude-sonnet-4-6     # Model ID passed to the API
    description: "Lightweight API calls for review and analysis"
    strengths: ["code_review", "summarization", "quick_decisions"]

  openai_api:
    type: api
    provider: openai
    model: gpt-4o
    description: "Alternative API for specific tasks"
    strengths: ["translation", "documentation"]

routing:
  rules:
    # Rules are matched in order. The first match wins.
    # "prefer" must be a key from the agents section above.
    - task_type: architecture
      prefer: claude_code
      reason: "Complex reasoning benefits from full tool access"
    - task_type: implementation
      prefer: claude_code
      when: "complexity >= medium"
    - task_type: code_review
      prefer: claude_api
      reason: "Lightweight, doesn't need file editing"

skills:
  # Skills prepend a slash command to the agent prompt, activating
  # a pre-defined workflow in the agent (e.g., Claude Code's /tdd skill).
  tdd:
    agent: claude_code
    invoke: "/tdd"
    use_when: ["test_writing", "implementation_with_tests"]
  code_review:
    agent: claude_code
    invoke: "/code-review"
    use_when: ["code_review"]
```

### Per-project config: `.ralph/project.yaml`

Each project can have its own config that layers on top of your global config. Generate a starter:

```bash
cd your-project/
ralph config init-project
```

This creates `.ralph/project.yaml`. The most useful fields:

```yaml
project:
  name: MyApp
  description: "What this project is"
  tech_stack: ["python", "fastapi", "postgres"]
  conventions: |
    Always use async/await. Never use print() — use structlog.
    All new endpoints need an integration test.
  test_command: "pytest"
  build_command: "make build"

  # Routing overrides apply on top of your global routing rules, for this project only.
  # Useful if a project needs a different agent than your global default.
  routing_overrides:
    - task_type: implementation
      prefer: claude_code
      reason: "This codebase is too complex for Codex"

  # Injected into Ralph's system prompt on every session with this project.
  orchestrator_context: |
    Always run xcodegen generate after adding or removing Swift files.
    This project uses Swift 6 strict concurrency — all new code must compile clean.
```

**Config merge order:** global routing rules run first, then project `routing_overrides` are appended. For everything else, the project config is additive — it doesn't replace global settings, it extends them.

### API keys

API agents read keys from environment variables. Set these in your shell profile:

```bash
export ANTHROPIC_API_KEY="sk-ant-..."
export OPENAI_API_KEY="sk-..."
```

CLI agents (Claude Code, Codex) handle their own authentication — they have their own login flows independent of Ralph.

### Validate your config

```bash
# Check for errors in both configs
ralph config validate

# See the final merged config Ralph will use
ralph config show
```

---

## Usage

```bash
# Run a task (dispatches to agents)
ralph run "add input validation to the user registration endpoint"

# Show what would happen without running anything
ralph run --dry-run "refactor the auth middleware"

# Clear previous session state and start fresh
ralph run --fresh "rewrite the payment module"

# Print full agent output (normally suppressed)
ralph run --verbose "add unit tests for UserService"

# Use a specific project directory (default: current directory)
ralph --project-dir /path/to/project run "fix the failing tests"

# Use a custom global config file
ralph --config /path/to/config.yaml run "add dark mode toggle"
```

**Config subcommands:**

```bash
ralph config show           # Print the resolved (merged) configuration
ralph config validate       # Check config for errors and warnings
ralph config init           # Create ~/.ralph/config.yaml from the example
ralph config init-project   # Create .ralph/project.yaml in current directory
```

---

## Agents: CLI vs API

Ralph supports two fundamentally different ways of talking to AI agents.

### CLI agents (Claude Code, Codex)

CLI agents are external programs installed on your machine. Ralph spawns them as subprocesses and passes your task as a prompt argument.

**How the dispatch works:**

```
ralph run "add dark mode toggle"
  └─ Builds argv: ["claude", "--print", "add dark mode toggle"]
  └─ Spawns subprocess via asyncio.create_subprocess_exec
  └─ Waits for it to finish
  └─ Captures stdout as the result
  └─ Nonzero exit code → task marked as FAILED
```

The agent sees your prompt and has full access to your filesystem, git history, and any tools it supports natively. Claude Code, for example, can read files, edit them, run tests, and commit — all driven by the prompt Ralph sends it.

**Requirements for CLI agents:**
- The `command` must be on your `PATH` (e.g., `which claude` should return a path)
- The agent must accept a prompt as a trailing argument
- Output goes to stdout; Ralph captures it after the process exits

### API agents (Anthropic, OpenAI)

API agents call cloud provider APIs directly using their Python SDKs. No subprocess is spawned. Ralph sends the task description as a message and receives the model's response as text.

**How the dispatch works:**

```
ralph run "review this PR for security issues"
  └─ Reads ANTHROPIC_API_KEY from environment
  └─ Calls anthropic.Anthropic().messages.create(...)
  └─ Returns the response text as task output
```

API agents are best for tasks that don't need file editing: code review feedback, summarization, quick decisions, documentation generation. They cannot modify files on their own — if you need file changes, use a CLI agent.

**Note:** API agent dispatch is stubbed in the current build. The routing, registry, and config support is complete; the SDK call implementation is the next development phase.

---

## Routing Rules

Routing rules tell Ralph which agent to use for each type of task. They live in your config and are matched in order — the first match wins.

```yaml
routing:
  rules:
    - task_type: architecture
      prefer: claude_code
      reason: "Complex reasoning benefits from full tool access"
    - task_type: code_review
      prefer: claude_api
      reason: "Lightweight — doesn't need file editing"
```

If no rule matches a task type, Ralph falls back to the first agent in your `agents` section.

**Project-level overrides** let you change routing for one project without touching your global config:

```yaml
# .ralph/project.yaml
project:
  routing_overrides:
    - task_type: implementation
      prefer: claude_code
      reason: "Codex doesn't understand this codebase"
```

Project overrides are appended after global rules, so they run as additional rules — they don't replace the global ones.

---

## Skills

A skill is a pre-prompted workflow that gets injected into the agent's prompt before your task description. For example, the `tdd` skill prepends `/tdd` to the prompt, which tells Claude Code to run its built-in TDD workflow.

```yaml
skills:
  tdd:
    agent: claude_code
    invoke: "/tdd"
    use_when: ["test_writing", "implementation_with_tests"]
```

When Ralph routes a task with type `test_writing`, it looks up skills registered for that use case, finds `tdd`, and dispatches Claude Code with `/tdd <your task>` as the prompt.

Skills are optional. If none match a task, Ralph sends the plain task description to the agent.

---

## State and Resuming

Ralph writes session state to `.ralph/state.json` in your project directory after each task. This file tracks the task graph: what's been done, what's in progress, what failed, and the full results from each agent.

```
your-project/
└── .ralph/
    └── state.json    ← written by Ralph, updated after each task
```

This file is machine-written. Don't edit it by hand.

**To start fresh** (discard the saved state):

```bash
ralph run --fresh "new task description"
```

**Resume** support (picking up an interrupted session) is on the roadmap — `--resume` flag is wired in the CLI but not yet implemented in the loop.

---

## Project Structure

```
ralph/
├── ralph/
│   ├── cli/
│   │   └── main.py              — Click CLI: ralph run, ralph config *
│   ├── core/
│   │   ├── orchestrator.py      — Serial task execution loop
│   │   ├── router.py            — Maps task types to agents via routing rules
│   │   └── task_graph.py        — Task, TaskGraph, TaskStatus, TaskResult models
│   ├── agents/
│   │   └── runner.py            — AgentRunner: CLI subprocess + API dispatch
│   ├── llm/
│   │   └── ollama_client.py     — Async Ollama client (wraps ollama library)
│   ├── skills/
│   │   └── registry.py          — SkillRegistry: skill lookup and resolution
│   ├── memory/
│   │   └── state.py             — StateManager: save/load state.json
│   └── config/
│       ├── schema.py            — Pydantic models for all config structures
│       └── loader.py            — Two-tier YAML config loading and merging
├── tests/                       — One test file per module, TDD throughout
├── docs/
│   ├── ralph-orchestrator-design.md   — Full architecture spec
│   └── ralph-mvp-implementation-plan.md
├── config.yaml.example          — Annotated global config template
└── pyproject.toml
```

---

## Development

```bash
# Install with dev dependencies
pip install -e ".[dev]"

# Run all tests
pytest

# Run tests for a specific module
pytest tests/test_orchestrator.py -v

# Lint and format
ruff check ralph/ tests/
ruff format ralph/ tests/
```

**Adding a new agent type:**

1. Add an entry to `config.yaml.example` and your `~/.ralph/config.yaml`
2. If it's a CLI agent: set `type: cli`, `command`, and `flags`. Ralph's `AgentRunner` handles the rest.
3. If it's a new API provider: add a branch in `ralph/agents/runner.py`'s `_run_api` method with the SDK call.

**Adding a new routing rule:**

Edit `~/.ralph/config.yaml` or your project's `.ralph/project.yaml`. No code changes needed.

**Running against a real Ollama instance:**

```bash
# Make sure Ollama is running and the model is pulled
ollama serve
ollama pull gemma4:27b

# Run Ralph against a real project
cd your-project/
ralph config init-project
ralph run "add error handling to the API endpoints"
```
