# Ralph Future Features

This document captures ideas worth preserving after the current Phase B replan.

It is not the active implementation plan.
It is a holding area for future capabilities, architectural extensions, and product ideas that should stay visible without being treated as current commitments.

## Positioning

Current baseline:
- local-first orchestration
- CLI-first execution
- API agents are optional
- Ralph acts primarily as the control plane around stronger execution agents

Current active direction:
- complete the remaining Phase B replan priorities such as `--resume`, journaling, and CLI hardening

This document is for what comes after that work, or for ideas that may influence design before they are scheduled.

## Future Capability Areas

### Durable Session Management

Candidate features:
- full `--resume` workflow with robust validation and recovery
- named sessions and run history
- clearer interrupted-run diagnostics
- safe restart and replay behavior

Why it matters:
- CLI-first orchestration is likely to be interrupted
- longer-lived sessions need better continuity than a single `state.json`

### Journaling And Long-Horizon Memory

Candidate features:
- session narrative logs
- milestone summaries
- compressed memory for longer projects
- explicit re-anchor points for the planner/evaluator

Why it matters:
- longer projects need more than raw task results
- future orchestration loops will need compact project memory, not just full transcripts

### Parallel Task Execution

Candidate features:
- run independent tasks concurrently
- join tasks after shared prerequisites complete
- concurrency controls per agent or per project
- failure handling for partially completed parallel branches

Why it matters:
- real project orchestration eventually needs throughput, not only correctness
- Phase B established the serial intelligence loop first; parallelism is the next major capability jump

### Stronger Multi-Agent Coordination

Candidate features:
- explicit handoff artifacts between agents
- task-local context bundles
- upstream/downstream result shaping
- specialized review or verifier passes
- shared progress summaries across agents
- per-agent work ownership with a unified project view

Why it matters:
- multi-agent orchestration becomes more useful when agents can operate with cleaner contracts instead of sharing only raw text
- a good project manager does not only assign work; they keep everyone aligned on what has already happened, what is blocked, and what must happen next

### Unified Cross-Agent Context

Candidate features:
- a canonical project memory Ralph maintains across runs and across agents
- compact handoff summaries so one model can pick up where another left off
- milestone and dependency tracking that is independent of any one agent transcript
- a shared view of completed work, open risks, assumptions, and pending decisions
- context packages Ralph can attach selectively to different agents based on task

Why it matters:
- different models will often work on the same project with different strengths
- Ralph should know the overall project state the way a project manager knows what each developer has done
- the orchestration layer becomes much more valuable when context continuity survives model switching

### Project-Manager Capabilities

Candidate features:
- dependency tracking between workstreams
- explicit handoff notes between agents
- risk registers and escalation reasons
- milestone checkpoints and progress reporting
- operator-facing summaries of what changed, what is blocked, and where attention is needed

Why it matters:
- long-running autonomous work needs more than task dispatch
- Ralph becomes more defensible as a product when it behaves like a capable project manager, not just a prompt relay

### Human Approval Workflows

Candidate features:
- approval gates before risky tasks
- explicit escalation queues
- pause/resume from approval decisions
- human review checkpoints before deploy or merge steps

Why it matters:
- not every failure should be a hard stop
- some workflows need structured human involvement, not just stderr output

## Skill System Evolution

The current implementation supports CLI skill-prefixed dispatch:
- Ralph resolves skills by `task_type`
- when a matching skill also matches the chosen agent, Ralph prepends the skill invoke string to the prompt

That is a good Phase B baseline, but it should likely evolve.

### Per-Task Skill Selection

Candidate direction:
- add an explicit skill field to the task model, such as `skill` or `skill_name`

Why it matters:
- multiple skills may match the same `task_type`
- retries should preserve the intended workflow
- planners or humans may want to choose a specific skill deliberately
- saved state should record which workflow Ralph intended to use

Example shape:

```python
Task(
    id="t1",
    description="Add dark mode persistence",
    task_type="implementation",
    agent="claude_code",
    skill="tdd",
)
```

### Native Skills Versus Ralph-Managed Skills

There are two distinct long-term models:

1. Native agent skills
   Example: Claude Code slash commands such as `/tdd`

2. Ralph-managed prompt skills
   Example: markdown instructions stored and injected by Ralph itself

Tradeoff summary:
- native skills are cheap, concise, and may trigger deeper agent-specific workflows
- Ralph-managed skills are portable, inspectable, and model-agnostic

### Hybrid Skill Model

Likely future direction:
- support both native and prompt-backed skills
- let each task choose the intended skill explicitly

Example config shape:

```yaml
skills:
  tdd:
    kind: native
    agent: claude_code
    invoke: "/tdd"
    use_when: ["test_writing"]

  portable_review:
    kind: prompt
    prompt_file: ".ralph/skills/review.md"
    use_when: ["code_review"]
```

Dispatch behavior under that model:
- `kind: native` -> prepend the invoke string
- `kind: prompt` -> render the markdown skill instructions into the dispatched prompt

### Token And Context Considerations

Prompt-backed skills introduce real overhead:
- larger prompt size
- slower dispatch
- less room for repo and task context
- repeated cost across retries and multi-task runs

Implication:
- native skills should remain preferred when a strong agent-native workflow exists
- prompt-backed skills are best used for portability, transparency, or cross-agent consistency

## Future Design Principle

Prefer designs that:
- preserve the CLI-first baseline
- keep API access optional
- make task intent explicit in saved state
- preserve unified project context even when multiple agents participate
- make handoffs and progress legible across model boundaries
- avoid hiding core orchestration behavior inside opaque agent-specific assumptions

## Notes

This document should evolve as ideas become concrete enough to either:
- move into the active Phase B replan work
- or become the basis for a true future phase once a new capability tier is ready
