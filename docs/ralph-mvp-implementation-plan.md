# Ralph MVP Implementation Plan

**Spec:** `docs/ralph-orchestrator-design.md`
**Scope:** Phase A — serial task loop, CLI, config, state, memory, skill registry
**Language:** Python 3.12+
**Repo:** `ralph/`

---

## Phase 1: Project Scaffold & Config System

**Goal:** Bootable CLI that loads and validates two-tier YAML config.

### Task 1.1: Project setup
- Initialize repo with `pyproject.toml` (project metadata, dependencies, entry point)
- Dependencies: `click`, `pyyaml`, `pydantic` (config validation), `ollama`, `anthropic`, `openai`
- Dev dependencies: `pytest`, `pytest-asyncio`, `ruff`
- Create directory structure per spec: `ralph/cli/`, `ralph/core/`, `ralph/agents/`, `ralph/skills/`, `ralph/memory/`, `ralph/config/`, `tests/`
- Add `__init__.py` files, basic `ralph/cli/main.py` with Click entry point
- `ralph "some task"` should parse the task string and print it back (smoke test)

### Task 1.2: Config schema and loader
- `ralph/config/schema.py` — Pydantic models for global config and project config
  - `OrchestratorConfig`: model, provider, endpoint, context_budget dict, re_anchor_interval, max_retries, journal_interval
  - `AgentConfig`: name, type (cli/api), command, flags, provider, model, description, strengths list
  - `RoutingRule`: task_type, prefer, when (optional condition string), reason
  - `SkillConfig`: agent, invoke, use_when list
  - `ProjectConfig`: name, description, tech_stack, conventions, test_command, build_command, routing_overrides, orchestrator_context
  - `RalphConfig`: top-level merged config combining global + project
- `ralph/config/loader.py` — Load `~/.ralph/config.yaml` (global) + `.ralph/project.yaml` (project), merge with project overrides taking precedence
  - Missing global config → error with helpful message
  - Missing project config → warning, use global defaults only
  - Validation errors → clear error messages pointing to the offending field

### Task 1.3: Config CLI integration
- `ralph config show` — print resolved (merged) config
- `ralph config validate` — validate both configs and report issues
- `ralph config init` — generate starter `~/.ralph/config.yaml` with commented examples
- `ralph config init-project` — generate starter `.ralph/project.yaml` in current directory

**Tests:**
- Config loading with valid YAML
- Config merging (project overrides global routing rules)
- Missing file handling (global missing = error, project missing = warning)
- Pydantic validation rejects invalid config (bad types, missing required fields)
- CLI smoke tests (entry point runs, config subcommands work)

---

## Phase 2: Task Graph & State Persistence

**Goal:** Data structures for task decomposition, dependency tracking, and disk persistence.

### Task 2.1: Task graph data model
- `ralph/core/task_graph.py` — Pydantic models:
  - `TaskStatus` enum: `pending`, `in_progress`, `passed`, `failed`, `retrying`, `escalated`
  - `TaskResult`: exit_code, files_modified list, test_summary (optional), error_message (optional), agent_used, duration_seconds
  - `Task`: id (uuid), description, task_type, depends_on (list of task ids), status, file_manifest (list of paths), result (optional TaskResult), retry_count, max_retries, created_at, updated_at
  - `TaskGraph`: tasks dict (id → Task), original_goal, created_at, updated_at
- Methods on TaskGraph:
  - `ready_tasks()` → tasks whose dependencies are all `passed` and own status is `pending`
  - `is_complete()` → all tasks `passed`
  - `is_stuck()` → no ready tasks but not complete (circular dep or all remaining failed/escalated)
  - `update_task(id, status, result)` → update with timestamp
  - `summary()` → one-line-per-task status string (for Ralph's rolling context)

### Task 2.2: State persistence
- `ralph/memory/state.py` — Read/write `TaskGraph` to `.ralph/state.json`
  - `save_state(graph, project_dir)` → atomic write (write to tmp, rename)
  - `load_state(project_dir) → TaskGraph | None` — returns None if no state file
  - `clear_state(project_dir)` — delete state file (for fresh starts)
- State file written after every task status change

### Task 2.3: Resume detection
- On startup, check for existing state file
- If found and has incomplete tasks: print summary, ask user to resume or start fresh
- `ralph --resume` flag to skip the prompt and resume automatically
- `ralph --fresh` flag to clear state and start over

**Tests:**
- TaskGraph dependency resolution (ready_tasks with various dep patterns)
- Circular dependency detection (is_stuck)
- State serialization roundtrip (save → load → identical graph)
- Atomic write doesn't corrupt on simulated failure
- Resume detection logic

---

## Phase 3: Agent Registry & Execution Backends

**Goal:** Pluggable agent interface with CLI and API backends that can execute tasks and return structured results.

### Task 3.1: Agent base interface
- `ralph/agents/base.py`:
  - `AgentTask` dataclass: description, file_manifest, context (upstream results, project conventions), skill (optional skill invoke string)
  - `AgentResult` dataclass: exit_code, stdout, stderr, files_modified, duration_seconds
  - `Agent` abstract base: `async execute(task: AgentTask) -> AgentResult`

### Task 3.2: CLI agent (Claude Code, Codex)
- `ralph/agents/cli_agent.py`:
  - `CLIAgent(Agent)` — wraps any CLI tool that accepts a prompt via stdin/args
  - Builds command from config: `[command] + [flags] + [prompt]`
  - Prompt construction: skill prefix (if any) + task description + file manifest + context
  - Runs via `asyncio.create_subprocess_exec`, captures stdout/stderr
  - Timeout handling (configurable per agent, default 5 minutes)
  - Parses `git diff --name-only` after execution to detect files modified
  - Returns `AgentResult`

### Task 3.3: API agent (Anthropic, OpenAI)
- `ralph/agents/api_agent.py`:
  - `APIAgent(Agent)` — direct SDK calls for lightweight tasks
  - `AnthropicBackend` — uses `anthropic` SDK, messages API
  - `OpenAIBackend` — uses `openai` SDK, chat completions API
  - No file editing capability — these agents return text responses only (code review feedback, summaries, decisions)
  - API key loading from environment variables (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`)
  - Returns `AgentResult` with stdout = response text, exit_code = 0 on success

### Task 3.4: Agent registry
- `ralph/agents/registry.py`:
  - Loads agent configs, instantiates appropriate `Agent` subclass for each
  - `get_agent(name) → Agent`
  - `list_agents() → dict of name → AgentConfig`
  - Validates at startup that CLI agents' commands exist on PATH

**Tests:**
- CLI agent: mock subprocess, verify command construction, timeout handling, git diff parsing
- API agent: mock SDK calls, verify prompt construction, error handling
- Registry: loads from config, validates command existence, unknown agent name errors
- Prompt construction: skill prefix prepended correctly, context included, file manifest formatted

---

## Phase 4: Ollama Integration & Prompt Templates

**Goal:** Ralph (Gemma) can be consulted for planning, routing, and evaluation via structured prompts.

### Task 4.1: Ollama client
- `ralph/core/llm.py`:
  - `LLMClient` wrapping `ollama` Python library
  - `async prompt(template: str, variables: dict, max_tokens: int) -> str`
  - Enforces context budget: estimate token count before sending, hard fail if over budget
  - Structured output parsing: Ralph's responses must be JSON — parse and validate
  - Connection error handling (Ollama not running, model not pulled)
  - Retry with backoff on transient failures (network blips)

### Task 4.2: Prompt templates
- `ralph/core/prompts/` directory with template files:
  - `planning.txt` — system prompt + goal + project context → expects JSON task list
  - `routing.txt` — task description + available agents + routing rules → expects JSON agent selection
  - `evaluation.txt` — task description + result summary → expects JSON verdict (pass/retry/escalate)
  - `retry.txt` — failure context + files → expects JSON adjusted instructions
  - `reanchor.txt` — original goal + progress summary → expects JSON confirmation/course correction
  - `journal.txt` — session summary → expects natural language journal entry
- Templates use simple `{variable}` substitution
- Each template has a hardcoded max token budget (from config)

### Task 4.3: Response parsing
- `ralph/core/response_parser.py`:
  - Parse planning response → list of `Task` objects with types and dependencies
  - Parse routing response → agent name + skill + reasoning
  - Parse evaluation response → verdict enum + reasoning + retry instructions (if retry)
  - Robust JSON extraction (handle markdown code fences, leading/trailing text)
  - Validation: parsed response must match expected schema, retry prompt on malformed output (once)

**Tests:**
- Prompt template rendering with various variables
- Token budget enforcement (reject over-budget prompts)
- Response parsing: valid JSON, JSON in code fences, malformed JSON, missing fields
- Planning response → valid task graph
- Routing response → valid agent selection
- Evaluation response → valid verdict
- Ollama connection failure handling

---

## Phase 5: Orchestrator Core Loop

**Goal:** The main loop that ties everything together: plan → route → dispatch → evaluate → advance.

### Task 5.1: Orchestrator class
- `ralph/core/orchestrator.py`:
  - `Orchestrator(config, agents, llm_client, state_manager)`
  - `async run(goal: str, project_dir: str)` — the main entry point
  - Implements the 8-step flow from the spec:
    1. **Load** — config + state (resume if exists)
    2. **Plan** — call LLM with planning prompt, parse into TaskGraph
    3. **Route** — for next ready task, call LLM with routing prompt
    4. **Dispatch** — invoke chosen agent with scoped context
    5. **Collect** — parse agent result, extract files modified + test output
    6. **Evaluate** — call LLM with evaluation prompt, get verdict
    7. **Advance** — update task graph, persist state, loop or finish
    8. **Complete** — write journal entry, print final summary

### Task 5.2: Context scoping
- `ralph/core/context.py`:
  - `build_agent_context(task, graph, project_config) → str` — constructs the scoped context an agent receives
  - Includes: task description, file manifest, project conventions, compressed upstream results
  - Excludes: unrelated tasks, full history, raw code
  - `build_ralph_context(graph, current_task) → str` — constructs Ralph's rolling context
  - Includes: plan summary (one line per task with status), current task details, current result
  - `compress_result(result: AgentResult) → str` — summarize a result to one line for rolling context

### Task 5.3: Re-anchoring
- Every N tasks (from config), inject re-anchor prompt before the next routing decision
- Re-anchor includes: original goal, tasks completed so far (one-line each), tasks remaining
- Prevents Ralph from drifting on longer sessions

### Task 5.4: Retry logic
- On `RETRY` verdict: increment retry count, call LLM for adjusted instructions, re-dispatch
- On max retries exceeded: mark task as `escalated`, print context to user, pause for input
- On `ESCALATE` verdict: immediate escalation regardless of retry count

### Task 5.5: CLI output
- Real-time status output during the loop:
  - `[PLAN] Decomposed into 5 tasks`
  - `[ROUTE] task_1 → claude_code (tdd skill)`
  - `[DISPATCH] Running claude_code...`
  - `[EVAL] task_1: PASSED`
  - `[RETRY] task_2: attempt 2/3 — test assertion mismatch`
  - `[ESCALATE] task_3: needs human input`
  - `[DONE] 5/5 tasks completed`
- Use `click.echo` with color (green for pass, yellow for retry, red for escalate)
- `--verbose` flag for full agent output

**Tests:**
- Orchestrator end-to-end with mocked LLM + mocked agents (happy path: all tasks pass)
- Retry flow: agent fails, LLM says retry, adjusted dispatch succeeds
- Escalation flow: max retries exceeded, loop pauses
- Re-anchoring triggers at correct intervals
- Context scoping: verify agent receives only relevant context
- Resume: load existing state, continue from where left off
- State persistence: verify state file updated after each task

---

## Phase 6: Skill Registry

**Goal:** Skills can be loaded from config and prepended to agent dispatches.

### Task 6.1: Skill registry
- `ralph/skills/registry.py`:
  - `SkillRegistry(config)` — loads skill definitions from config
  - `match_skill(task_type: str, agent_name: str) → SkillConfig | None` — find best skill for task type + agent combo
  - `build_invoke_prefix(skill: SkillConfig) → str` — returns the slash command string to prepend

### Task 6.2: Skill validation
- At startup, validate that each skill's `agent` exists in the agent registry
- For CLI agents: optionally probe whether the skill command is recognized (best-effort, non-blocking)
- Missing/invalid skills produce warnings, not errors

### Task 6.3: Integration with dispatch
- Router output includes skill recommendation
- Dispatch layer prepends skill invoke string to agent prompt
- Skill usage logged in task result for debugging

**Tests:**
- Skill matching by task type
- Skill matching respects agent constraint (skill only applies to its configured agent)
- No matching skill → None (agent runs without skill prefix)
- Skill prefix correctly prepended to CLI agent command
- Invalid skill config produces warning at startup

---

## Phase 7: Project Memory & Journal

**Goal:** Ralph can resume projects across sessions with context recovery.

### Task 7.1: Journal writer
- `ralph/memory/journal.py`:
  - `write_journal_entry(llm_client, graph, project_dir)` — calls Ralph with journal prompt, writes entry to `.ralph/journal/YYYY-MM-DD-HHMMSS.md`
  - Entry includes: what was accomplished, decisions made, issues encountered, what's next
  - Triggered at session end (or configurable interval)

### Task 7.2: Resume prompt builder
- `ralph/memory/resume.py`:
  - `build_resume_prompt(project_config, state, journal_entries) → str`
  - Loads: project config conventions, state file summary, last 2-3 journal entries
  - Fits within context budget (truncate journal entries if needed, state summary is always compact)
  - Returns a focused prompt that orients Ralph on where the project stands

### Task 7.3: Session lifecycle
- On session start: check for state + journal, offer resume
- On session end (all tasks done or user quits): write journal entry, update state
- On crash/interrupt: state file reflects last completed task (safe to resume)
- `ralph journal show` — print recent journal entries for a project
- `ralph journal clear` — clear journal history (keep state)

**Tests:**
- Journal entry generation (mock LLM, verify file written with timestamp name)
- Resume prompt construction (verify it includes state + journal + config)
- Resume prompt respects context budget (truncation when journal is long)
- Session lifecycle: clean start → journal written at end
- Crash recovery: state file is consistent after simulated interrupt

---

## Phase 8: Integration Testing & Polish

**Goal:** End-to-end validation and usability polish.

### Task 8.1: End-to-end integration test
- Test with mocked Ollama (deterministic responses) + mocked subprocess (simulated CLI agent output):
  - Full loop: goal → plan → route → dispatch → evaluate → complete
  - Retry scenario: first attempt fails, retry succeeds
  - Escalation scenario: all retries fail, user prompted
  - Resume scenario: start session, interrupt, resume, complete
- These tests validate the full wiring, not individual components

### Task 8.2: Error handling audit
- Ollama unreachable → clear error message + instructions
- Agent timeout → task marked failed, retry with timeout note
- Invalid agent output (unparseable) → escalate with raw output shown
- Config errors → specific field + file path in error message
- Disk full / permission errors on state write → graceful degradation message

### Task 8.3: CLI polish
- `ralph status` — show current project state (tasks, progress)
- `ralph history` — show completed sessions with journal summaries
- `--dry-run` flag — plan and route but don't dispatch (preview what would happen)
- `--yes` flag — skip resume confirmation prompts
- Help text for all commands and flags
- Version command (`ralph --version`)

### Task 8.4: Documentation
- README.md: installation, quick start, config reference, architecture overview
- Example configs: global config, project configs for different tech stacks
- Troubleshooting guide: common issues (Ollama not running, model not pulled, API keys missing)

**Tests:**
- CLI help output renders correctly
- `--dry-run` produces plan without execution
- `ralph status` with no state → clean message
- `ralph status` with active state → formatted progress

---

## Dependency Graph

```
Phase 1 (Config) ─────────────────────────────┐
Phase 2 (Task Graph) ─────────────────────────┤
Phase 3 (Agents) ─────────────────────────────┼──→ Phase 5 (Orchestrator Core)
Phase 4 (Ollama + Prompts) ───────────────────┘         │
                                                         ├──→ Phase 8 (Integration)
Phase 6 (Skills) ──→ integrates into Phase 5 dispatch    │
Phase 7 (Memory) ──→ integrates into Phase 5 lifecycle ──┘
```

Phases 1-4 can be built in any order (they're independent). Phase 5 requires all four. Phases 6-7 integrate into Phase 5. Phase 8 is final validation.

## Key Implementation Notes

- **All I/O is async** — `asyncio` throughout, agents run as async subprocess/API calls
- **Pydantic everywhere** — config, task graph, agent results all validated with Pydantic models
- **No global state** — everything flows through constructor injection (config → orchestrator → agents)
- **Test isolation** — all external dependencies (Ollama, subprocess, APIs) are mockable via dependency injection
- **Atomic state writes** — write to temp file, rename. Never corrupt state on crash.
