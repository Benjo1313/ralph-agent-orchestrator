# Ralph: Local LLM Multi-Agent Development Orchestrator

**Date:** 2026-04-05
**Status:** Design approved
**Project:** Standalone (separate repo, project-agnostic)

## Overview

Ralph is a Python CLI tool that orchestrates multiple AI coding agents in a stateful, self-correcting development loop. The orchestrator manages workflow, context, routing, retries, and escalation around stronger execution agents.

The default operating model is **local-first and CLI-first**:

- installed coding-agent CLIs handle the deepest implementation reasoning
- Ralph handles orchestration, prompt shaping, and state continuity around them
- direct provider APIs are optional integrations, not a requirement
- current implementation still uses a local Gemma model for some planning and evaluation paths

## Motivation

- **Reduce human-in-the-loop overhead** — autonomous plan-execute-evaluate loop
- **Smart model routing** — use the right model/agent for each task type via config
- **Context efficiency** — local orchestrator stays lean and works from compressed task/result summaries
- **Pluggable execution** — Claude Code, Codex, optional direct API, or future backends behind a uniform interface
- **Project portability** — works on any codebase via per-project config profiles
- **Low-friction onboarding** — useful even when a user has no provider API billing enabled

## Architecture

### Core Components

1. **CLI Entry Point** — Parses user input (task description + flags), loads config, kicks off the orchestration loop
2. **Orchestrator Core** — Main loop: plan, dispatch, evaluate, decide. Consults Gemma via Ollama at each decision point
3. **Task Graph** — In-memory data structure (persisted to JSON) tracking tasks, statuses, dependencies, results, and ownership
4. **Agent Registry** — Pluggable execution backends registered via config. Each implements a common interface: `execute(task) -> result`
5. **Skill Registry** — Maps task types to pre-prompted agent skills (e.g., TDD workflow, code review). In the target model, dispatches agents with the appropriate skill pre-loaded
6. **Router** — Takes a task plus config routing rules and picks which agent to use. The current implementation is config-driven, with room for richer reasoning later
7. **Evaluator** — Assesses each task result: pass, retry (with adjusted instructions), or escalate to human. Gemma handles this with structured output
8. **Config System** — Two-tier: global orchestrator config + per-project config
9. **Memory System** — Two-layer project memory for context recovery across sessions

### Execution Backends

| Backend | Type | Use Case |
|---------|------|----------|
| Claude Code | CLI (`claude --print`) | Complex implementation, architecture, debugging, TDD |
| Codex | CLI | Straightforward implementation, boilerplate |
| Claude API | Direct API (Anthropic SDK, optional) | Code review, summarization, quick analysis |
| OpenAI API | Direct API (OpenAI SDK, optional) | Alternative for specific tasks |

CLI backends are the primary path. API backends are optional and depend on separate provider billing.

New backends can be added via config without code changes — any CLI tool or API that accepts a prompt and returns a result.

## Execution Flow

```
User runs: ralph "add dark mode toggle to settings"

1. LOAD    — Read global config + project config + project state (if resuming)
2. PLAN    — Gemma decomposes task into ordered subtasks with types and dependencies
3. ROUTE   — For each ready task, Ralph applies routing rules to pick an agent
4. DISPATCH — Python invokes the chosen agent (usually subprocess for CLI, optionally SDK call for API)
             Agent receives scoped context: only relevant files, task description,
             upstream results
5. COLLECT — Parse agent result: exit code, files modified (git diff), test output,
             errors
6. EVALUATE — Gemma judges result summary: PASS / RETRY / ESCALATE
7. ADVANCE — Update task graph, write state to disk, loop to step 3 if tasks remain
8. COMPLETE — Write journal entry, report results to user
```

The Python code drives the loop. Current implementation still consults Gemma at planning and evaluation decision points, but the intended architecture is that Ralph remains the control plane while stronger execution agents do the heaviest project reasoning.

### Human Escalation Triggers

- Max retries exceeded on a task
- Merge conflict detected
- Ambiguous requirement Ralph can't resolve
- Test infrastructure broken (not a code bug)
- Agent returns unexpected/unparseable output

On escalation, Ralph presents: what it was trying to do, what it tried, what failed, and asks for guidance.

## Context Management

### The Core Constraint

Gemma 4 27B has a 128K context window but degrades on complex reasoning with large contexts. Every prompt to Ralph must be focused and minimal.

### Principles

**1. Ralph never sees raw code.** It sees task descriptions, file manifests, status enums, and compressed summaries. A 200-line test output becomes "3 tests failed: test_x, test_y, test_z — assertion errors on lines 45, 82, 110."

**2. Rolling context, not accumulating.** Ralph's context at any decision point contains: current plan summary, current task, current result. Completed tasks are compressed to one-line status entries. Full details live on disk.

**3. Separate prompt templates per decision type:**
- **Planning:** goal + project config → task graph
- **Routing:** task description + available agents/skills → agent selection
- **Evaluation:** task description + result summary → pass/retry/escalate
- **Retry:** failure reason + relevant files → adjusted instructions

**4. Config-driven context caps.** Each prompt type has a max token budget. Exceeding it is a hard failure, not a silent degradation.

**5. Re-anchoring.** Every N tasks (configurable), Ralph gets a prompt restating the original goal and current progress. Prevents drift on longer sessions.

### Agent Context Scoping

Each dispatched task includes only what that agent needs:
- Explicit file manifest ("you own these files, don't touch anything else")
- Task description and acceptance criteria
- Relevant upstream task results (compressed)
- Project conventions from config

If two tasks need the same file, they run sequentially (enforced at the routing layer). This becomes critical when parallelism is added later.

## Project Memory & Context Recovery

### The Problem

Ralph works on Project A, switches to Project B for days, returns to Project A. Its context is empty. It needs efficient recovery.

### Two-Layer Memory

**Layer 1: State File (`.ralph/state.json`) — structured, machine-written**
- Task graph with statuses, timestamps, agent assignments, pass/fail results
- File ownership manifest
- Current position in the plan
- Retry history

Written by the Python orchestrator code after every task cycle. Deterministic, not LLM-generated.

**Layer 2: Journal (`.ralph/journal/`) — human-readable session summaries**
- Markdown entries written at session end, with optional checkpoint entries when `journal_interval` is numeric
- Captures planning changes, completed tasks, retries, escalations, and overall run outcome
- Advisory context, not authoritative — state file is the source of truth

### Resume Flow

When Ralph resumes a project:
1. Load static project config (conventions, commands, structure)
2. Load state file — programmatically extract "here's where you left off"
3. Continue from the saved task graph
4. Use journal entries as a human review surface if needed

State file determines *what to do next*. Journal gives the operator a compact record of what happened in each run.

## Skill Registry

Ralph can dispatch agents with pre-prompted skills — curated prompt templates paired with specific workflows (e.g., from plugins like superpowers or everything-claude-code).

### How It Works

Instead of just picking "claude_code," the target model lets Ralph pick "claude_code with the `tdd` skill." The dispatch layer can then invoke Claude Code with that skill pre-loaded.

### Config

```yaml
skills:
  tdd:
    agent: claude_code
    invoke: "/tdd"
    use_when: ["test_writing", "implementation_with_tests"]

  code_review:
    agent: claude_code
    invoke: "/code-review"
    use_when: ["code_review"]

  plan:
    agent: claude_code
    invoke: "/superpowers:write-plan"
    use_when: ["planning", "architecture"]
```

### Invocation Mechanism

For CLI agents, the mechanism is to prepend the skill invoke string at the top of Ralph's execution envelope so agent-native slash commands still trigger correctly. Ralph then delivers that envelope either as a trailing argument or through stdin, depending on agent config.

### Constraints

- MVP: only skills that work in non-interactive / headless mode
- Skills requiring human back-and-forth are excluded initially
- Expand to interactive skills later by having Ralph simulate expected responses
- Skill availability is validated at startup — missing skills produce warnings, not errors

## Configuration System

### Global Config (`~/.ralph/config.yaml`)

```yaml
orchestrator:
  model: gemma4:27b
  provider: ollama
  endpoint: http://<gpu-machine>:11434
  context_budget:
    planning: 4096
    routing: 2048
    evaluation: 3072
    retry: 2048
  re_anchor_interval: 5
  max_retries: 3
  journal_interval: session_end

agents:
  claude_code:
    type: cli
    command: claude
    flags: ["--print"]
    prompt_mode: argument
    description: "Full-featured coding agent with git awareness and tool use"
    strengths: ["architecture", "complex_logic", "refactoring", "debugging"]

  codex:
    type: cli
    command: codex
    prompt_mode: argument
    description: "Fast implementation agent"
    strengths: ["straightforward_implementation", "boilerplate"]

  claude_api:
    type: api
    provider: anthropic
    model: claude-sonnet-4-6
    description: "Lightweight API calls for review and quick analysis"
    strengths: ["code_review", "summarization", "quick_decisions"]

  openai_api:
    type: api
    provider: openai
    model: gpt-4o
    description: "Alternative API for specific tasks"
    strengths: ["translation", "documentation"]

routing:
  rules:
    - task_type: architecture
      prefer: claude_code
      reason: "Complex reasoning benefits from full tool access"
    - task_type: test_writing
      prefer: claude_code
      reason: "Needs to read existing code and run tests"
    - task_type: implementation
      prefer: codex
      when: complexity < medium
    - task_type: implementation
      prefer: claude_code
      when: complexity >= medium
    - task_type: code_review
      prefer: claude_api
      reason: "Lightweight, doesn't need file editing"

skills:
  tdd:
    agent: claude_code
    invoke: "/tdd"
    use_when: ["test_writing", "implementation_with_tests"]
  code_review:
    agent: claude_code
    invoke: "/code-review"
    use_when: ["code_review"]
```

### Project Config (`.ralph/project.yaml`)

```yaml
project:
  name: GetReady
  description: "iOS reverse-scheduling app"
  tech_stack: ["swift", "swiftui", "swiftdata"]

  conventions: |
    Swift 6, strict concurrency. Swift Testing not XCTest.
    ViewModels are @Observable @MainActor final class.
    Run xcodegen after adding/removing files.

  test_command: "xcodebuild test -project GetReady.xcodeproj -scheme GetReady -destination '...'"
  build_command: "xcodegen generate && xcodebuild build ..."

  routing_overrides:
    - task_type: implementation
      prefer: claude_code
      reason: "Swift/iOS work benefits from Claude's stronger Swift knowledge"

  orchestrator_context: |
    This is a SwiftUI iOS app. Always run xcodegen after file changes.
    Tests use Swift Testing framework (@Suite, @Test, #expect).
    Follow TDD: write failing tests first, then implement.
```

### Config Design Decisions

- **YAML over JSON** — human-editable, comments supported
- **Agent `strengths` are hints** — they help planning and operator understanding even when routing remains rule-driven
- **Project config overrides global** — per-project routing takes precedence
- **`orchestrator_context` is a system prompt fragment** — shapes Ralph's behavior per-project

## Phased Rollout

| Phase | Scope |
|-------|-------|
| **A (Foundation)** | Config system, CLI interface, state persistence, serial task execution skeleton, routing rules, and agent dispatch foundations. |
| **B (Intelligence Loop)** | Planner-driven task decomposition, evaluator-driven pass/retry/escalate decisions, retry handling, optional API dispatch, and a CLI-first operating model. Current direction updates prioritize skill-aware CLI dispatch, durable resume, journaling, and CLI adapter hardening. |
| **C (Advanced Orchestration)** | Parallel task execution, stronger multi-agent coordination, durable recovery across longer sessions, human approval workflows, richer long-horizon memory, and monitoring surfaces. |

## Tech Stack

- **Python 3.12+** — orchestrator implementation
- **Ollama** — local Gemma 4 27B hosting
- **Anthropic SDK** — optional direct Claude API calls
- **OpenAI SDK** — optional direct GPT API calls
- **PyYAML** — config parsing
- **Click or Typer** — CLI framework
- **subprocess** — CLI agent invocation

## Project Structure (Planned)

```
ralph/
├── cli/              — CLI entry point, argument parsing
├── core/
│   ├── orchestrator.py   — Main loop logic
│   ├── planner.py        — Task decomposition (Gemma interaction)
│   ├── router.py         — Agent + skill selection
│   ├── evaluator.py      — Result assessment
│   └── task_graph.py     — Task data structures and state management
├── agents/
│   ├── base.py           — Agent interface (execute → result)
│   ├── cli_agent.py      — CLI subprocess wrapper (Claude Code, Codex)
│   └── api_agent.py      — Direct API wrapper (Anthropic, OpenAI)
├── skills/
│   └── registry.py       — Skill loading and invocation
├── memory/
│   ├── state.py          — State file read/write
│   └── journal.py        — Journal entry generation and retrieval
├── config/
│   ├── loader.py         — YAML config loading and merging
│   └── schema.py         — Config validation
└── tests/
```

## Out of Scope (MVP)

- Web dashboard / UI
- Parallel agent execution
- Interactive skill support
- Cross-project learning
- Agent-to-agent communication
- Custom agent development SDK
- Authentication / multi-user support
