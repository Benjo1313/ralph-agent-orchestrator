# Phase B Replan: CLI-First Ralph

**Date:** 2026-04-15
**Status:** Active direction update
**Supersedes:** Priority assumptions after `docs/ralph-phase-b-status.md`
**Does not replace:** `docs/ralph-phase-b-implementation-plan.md` or `docs/ralph-phase-b-status.md`

---

## Why This Replan Exists

Phase B was implemented successfully. Ralph now has the full serial intelligence loop:

`plan -> route -> dispatch -> evaluate -> retry or advance`

However, the original Phase B framing treated direct provider APIs as a normal part of the operating model. In practice, many users will have:

- a ChatGPT subscription but no OpenAI API billing
- a Claude subscription but no Anthropic API billing
- local or installed coding-agent CLIs available before API access is enabled

That changes product priorities more than architecture. Ralph should be optimized first for the environment users are most likely to have on day one.

## What Remains True From Phase B

The following remain correct and already implemented:

- local LLM planning through Ollama
- local LLM evaluation and retry decisions
- serial task graph execution
- CLI agent dispatch
- optional API agent dispatch
- state persistence and escalation handling

This replan is not a rollback. It is a direction change about what Ralph should treat as the default execution model.

It is also a correction in where Ralph should carry intelligence. Ralph should not try to out-plan frontier execution agents such as Claude Code, Codex, or GPT-5.4-class systems. Its primary value is orchestration: preserving state, shaping prompts, routing work, deciding when to retry or escalate, and keeping long-running CLI-driven work understandable and recoverable.

## Revised Phase B Baseline

Ralph's baseline is now:

- **local-first orchestration**
- **CLI-first execution**
- **API-optional integrations**
- **control-plane autonomy over agent-first reasoning**

In concrete terms:

- The orchestrator should assume the strongest available execution agent often does the deepest reasoning and planning.
- The primary execution backends should be installed agent CLIs such as Claude Code, Codex, and future local/headless tools.
- Ralph should optimize prompt scaffolding, state management, retries, resume, and context continuity around those agents.
- API agents remain supported, but they are not required for the product to be useful or complete.

Current implementation note:

- Ralph can use a local model for planning and evaluation, but those control-plane stages are now optional.
- That remains a valid implementation path and fallback mode.
- But it should not be treated as the long-term product identity if stronger CLI agents are already available in the workflow.

## Product Positioning

Ralph should be described as:

> A local orchestrator that helps strong coding agents operate more autonomously, consistently, and recoverably, primarily through CLI tools. Cloud APIs are optional.

This is a better match for real user setup, lower-friction onboarding, and the current implementation.

## Replanned Phase B Priorities

The next work should continue under the Phase B umbrella, but with revised ordering.

### B4: Skill-Aware CLI Dispatch

**Status:** implemented for the current CLI-first path.

Why it matters:

- Skills are more valuable when execution is mostly through agent CLIs.
- Ralph now prepends configured skill invoke strings during CLI dispatch when a task's `task_type` and chosen agent match the skill config.

Target outcomes:

- resolve skills by `task_type`
- prepend skill invoke strings to dispatched prompts when appropriate
- ensure agent selection and skill selection are coherent
- add tests covering skill-aware dispatch behavior

### B5: Durable Resume

**Status:** implemented for the current state-file model.

Why it matters:

- CLI-driven orchestration is more likely to be interrupted and resumed across sessions.
- Resume is more immediately valuable than deeper API polish.

Target outcomes:

- resume the latest saved task graph safely
- reject ambiguous or corrupt resume states cleanly
- document how fresh runs and resumed runs differ

### B6: Journal And Session Narrative

**Status:** implemented for human-readable session summaries under `.ralph/journal/`.

Why it matters:

- CLI-first orchestration needs good observability because execution happens in external tools.
- Users need a concise explanation of what Ralph attempted, what happened, and where intervention is needed.

Current behavior:

- writes a markdown journal entry at session end
- optionally writes checkpoint entries when `journal_interval` is a positive integer
- includes task planning changes, completions, retries, escalations, and final status
- keeps the journal separate from machine state

### B7: CLI Adapter Hardening

**Status:** implemented for the current CLI-first path.

Why it matters:

- CLI execution is Ralph's primary backend and needs clearer contracts than a raw prompt passthrough.
- Strong execution agents perform better when Ralph provides compact structured context and clear non-interactive expectations.

Current behavior:

- standardizes CLI prompt construction with a compact execution envelope
- carries project context, task metadata, retry attempt, dependencies, and acceptance criteria into CLI dispatch
- keeps skill invokes at the top of the prompt so agent-native slash commands still work
- supports two CLI prompt delivery modes: trailing argument and stdin
- surfaces richer subprocess failures, including exit code, prompt mode, and captured stdout/stderr
- validates CLI and API agent config shape more strictly

### B8: Prompt And Context Tightening For Ralph-Controlled Decisions

**Status:** implemented for the current control-plane path.

Why it matters:

- Ralph needs prompt discipline and parsing resilience even when a local control-plane model is not the strongest model in the workflow.
- Better prompt shaping helps Ralph coordinate stronger execution agents without pretending to replace them.

Current behavior:

- planner prompts explicitly frame Ralph as a control-plane planner that should avoid over-decomposing work
- evaluator prompts distinguish PASS, RETRY, and ESCALATE more explicitly and ask for tighter retry instructions
- planner and evaluator both attempt one schema-repair pass before falling back
- planner and evaluator can extract JSON objects from fenced or noisy model output
- planner validates task ids, task types, and dependency references more strictly
- evaluator compresses large outputs more defensibly before asking for a verdict
- CLI retry prompts render retry guidance as a separate section instead of burying it inside the task body
- `planning_mode` and `evaluation_mode` can be disabled so CLI-first runs do not require any local control-plane model

## Deprioritized Under This Replan

The following are still valid features, but they are no longer near-term priorities:

- API-first onboarding paths
- provider-specific API polish beyond basic support
- assuming Anthropic/OpenAI billing is present
- examples that require cloud APIs to understand or demo Ralph

## Documentation Changes Needed

Docs should reflect the new default operating model.

Highest priority updates:

- `README.md`
- `docs/ralph-orchestrator-design.md`
- `config.yaml.example`
- `CLAUDE.md`

Required message changes:

- CLI agents are the primary path.
- API agents are optional.
- Ralph is the orchestration layer, not the primary source of deep implementation planning.
- skills and resume are higher priority than API expansion.

## Success Criteria For The Replanned Phase B

Phase B should be considered fully aligned with product reality when:

- a user can configure Ralph with only local Ollama plus one or more CLI agents
- Ralph can dispatch, retry, journal, and resume around strong CLI agents without requiring cloud APIs
- skill-aware dispatch works for supported CLI agents
- session state and journals make interrupted runs understandable and recoverable
- Ralph improves autonomy and consistency without trying to replace the CLI agent's own reasoning
- docs present API usage as optional rather than expected

## Phase C Candidates To Preserve

These should stay in view for the next true capability tier, but they do not need to be pulled into the current replan:

- parallel task execution
- multi-agent coordination with shared context, unified progress tracking, and file ownership
- long-horizon memory and richer narrative logging
- human approval workflows for risky operations
- stronger recovery and session management across long-running projects
- project-manager-style coordination skills such as dependency tracking, handoff clarity, and risk surfacing

Those are good Phase C candidates because they add a new level of orchestration capability rather than simply correcting Phase B priorities.

## Summary

Phase B is still the right bucket for the next set of work.

What changed is not the existence of the intelligence loop. What changed is the product baseline:

- before: intelligence loop with API support treated as normal
- now: intelligence loop optimized for local-first, CLI-first operation with Ralph acting as the control plane around stronger execution agents

That is a Phase B replan, not a new phase.
