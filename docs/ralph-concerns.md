# Ralph Concerns

This document captures architectural concerns, design tensions, and implementation shortcuts that are worth revisiting later.

It is not a roadmap. Use `docs/ralph-phase-b-replan.md` for current priorities and `docs/ralph-future-features.md` for larger future capabilities.

## Active Concerns

### CLI execution is still one-shot and non-streaming

Current state:
- Ralph sends one prompt, waits for process exit, then evaluates final stdout/stderr

Why this matters:
- no live visibility during long runs
- no timeout or heartbeat policy yet
- limited ability to distinguish "slow but healthy" from "hung"

Good future direction:
- add timeouts, heartbeat expectations, and optional streaming logs

### Prompt envelopes are generic rather than agent-specific

Current state:
- Ralph sends a standardized CLI execution envelope to all CLI agents

Why this matters:
- useful as a baseline, but different agents may respond better to different prompt shapes
- some agents may prefer stricter summaries, others shorter task framing

Good future direction:
- add agent-specific envelope tuning while preserving one shared contract

### Skill selection is inferred rather than explicit per task

Current state:
- Ralph resolves skills from `task_type` and chosen agent

Why this matters:
- ambiguous when multiple skills apply to the same task type
- retries and human overrides cannot record an exact intended skill yet

Good future direction:
- add first-class per-task skill selection

### Unified cross-agent context is not implemented yet

Current state:
- Ralph has state and journals, but no stronger shared context model across multiple execution agents

Why this matters:
- handoffs remain thinner than a true project manager would provide
- long-running work across multiple agents can lose continuity

Good future direction:
- build a compact shared project context layer with handoffs, progress summaries, and pending decisions

### Planning disablement is only a bypass, not agent-led planning yet

Current state:
- disabling `planning_mode` keeps Ralph on a single routed task instead of asking the execution agent for a structured plan

Why this matters:
- this removes the local-model dependency, but it does not yet replace it with a stronger agent-first planning contract
- Ralph still lacks an explicit way to capture a frontier agent's plan as durable orchestration state

Good future direction:
- add an agent-led planning mode where Ralph asks the execution agent for a compact structured plan, then persists and manages it

### Evaluation disablement falls back to raw subprocess success

Current state:
- disabling `evaluation_mode` treats zero-exit dispatch as success and non-zero dispatch as failure

Why this matters:
- some agents can exit successfully while still reporting they were blocked or only partially completed the task
- Ralph loses the distinction between "command succeeded" and "task truly passed"

Good future direction:
- add agent-aware completion checks or a lighter-weight structured self-report path before introducing a richer shared-context layer

### State and journal formats are not versioned yet

Current state:
- `state.json` and journal entries persist useful data, but there is no explicit schema versioning or migration path

Why this matters:
- compatibility gets harder as task fields, retry metadata, and future context structures evolve
- resume and long-running usage become riskier across upgrades

Good future direction:
- add explicit persisted schema versions plus migration helpers before expanding session memory further

## Recently Addressed

### Local planning and evaluation are now optional control-plane modes

What changed:
- `planning_mode` and `evaluation_mode` can now be set to `disabled`
- Ralph only instantiates Ollama, Planner, and Evaluator when at least one local control-plane stage is enabled
- CLI-first runs can now route, dispatch, journal, resume, and persist state without requiring any local model config

Why this matters:
- Ralph no longer hard-depends on a local control-plane model for every run
- local planning/evaluation remain available as a fallback instead of being forced into the baseline
- this is a cleaner bridge toward later agent-led planning and stronger shared project context

### Retry guidance is now first-class task state

What changed:
- retry guidance now lives on `Task.retry_guidance`
- task descriptions stay stable across retries
- CLI prompt rendering still understands the older embedded format for compatibility with saved state from earlier runs

Why this matters:
- task intent is cleaner
- retry metadata is easier to reason about and persist
- this removes one piece of orchestration state that was leaking into user-facing task text

## Review Guidance

When revisiting this file:
- move concrete committed work into the replan or implementation docs
- move large future capability ideas into `docs/ralph-future-features.md`
- keep this file focused on risks, tensions, and design debt
