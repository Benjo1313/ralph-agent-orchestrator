"""Ralph CLI entry point."""
import asyncio
import sys
import uuid
import warnings
from pathlib import Path

import click
import yaml

from ralph.agents.runner import AgentRunner
from ralph.config.loader import ConfigError, load_config
from ralph.core.evaluator import Evaluator
from ralph.core.orchestrator import Orchestrator
from ralph.core.orchestrator import OrchestratorConfig as OrchestratorRunConfig
from ralph.core.planner import Planner
from ralph.core.task_graph import Task, TaskGraph, TaskStatus
from ralph.llm.ollama_client import OllamaClient
from ralph.memory.state import StateError, StateManager


@click.group()
@click.version_option(version="0.1.0", prog_name="ralph")
@click.option("--config", "config_path", type=click.Path(path_type=Path), default=None)
@click.option("--project-dir", type=click.Path(path_type=Path), default=None)
@click.pass_context
def cli(ctx: click.Context, config_path, project_dir):
    """Ralph — local LLM multi-agent development orchestrator.

    Run a task:

        ralph run "add dark mode toggle to settings"

    Manage config:

        ralph config show
    """
    ctx.ensure_object(dict)
    if project_dir is None:
        project_dir = Path.cwd()
    ctx.obj["config_path"] = config_path
    ctx.obj["project_dir"] = project_dir


@cli.command("run")
@click.argument("task", required=False)
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Plan and route without dispatching agents.",
)
@click.option(
    "--resume",
    is_flag=True,
    default=False,
    help="Resume previous session automatically.",
)
@click.option("--fresh", is_flag=True, default=False, help="Clear state and start fresh.")
@click.option("--yes", is_flag=True, default=False, help="Skip confirmation prompts.")
@click.option("--verbose", is_flag=True, default=False, help="Show full agent output.")
@click.pass_context
def run_task(ctx: click.Context, task, dry_run, resume, fresh, yes, verbose):
    """Run the orchestration loop for TASK."""
    config_path = ctx.obj.get("config_path")
    project_dir = ctx.obj.get("project_dir", Path.cwd())

    with warnings.catch_warnings(record=True):
        warnings.simplefilter("always")
        try:
            cfg = load_config(global_config_path=config_path, project_dir=project_dir)
        except ConfigError as e:
            click.echo(f"Error: {e}", err=True)
            sys.exit(1)

    if dry_run:
        click.echo(f"[DRY RUN] Task: {task}")
        click.echo("(Dispatch skipped — dry-run mode)")
        return

    state_dir = Path(project_dir) / ".ralph"
    state_manager = StateManager(state_dir=state_dir)

    if resume and fresh:
        click.echo("Error: --resume and --fresh cannot be used together.", err=True)
        sys.exit(1)
    if resume and task is not None:
        click.echo("Error: TASK cannot be provided when using --resume.", err=True)
        sys.exit(1)
    if not resume and task is None:
        click.echo("Error: TASK is required unless using --resume.", err=True)
        sys.exit(1)

    if fresh and state_manager.has_saved_state:
        state_manager.clear()
        click.echo("Cleared previous session state.")

    if dry_run:
        if resume:
            graph = _load_saved_graph(state_manager)
            click.echo(f"[DRY RUN] Resume session: {graph.goal}")
            pending = len([t for t in graph.tasks.values() if not t.is_terminal])
            click.echo(f"Pending tasks: {pending}")
        else:
            click.echo(f"[DRY RUN] Task: {task}")
            click.echo("(Dispatch skipped â€” dry-run mode)")
        return

    graph, run_label = _resolve_run_graph(
        task=task,
        resume=resume,
        state_manager=state_manager,
        agents=cfg.agents,
    )
    if graph.is_complete:
        click.echo(f"Saved session already complete: {graph.goal}")
        return

    orch_config = OrchestratorRunConfig(
        model=cfg.orchestrator.model,
        endpoint=cfg.orchestrator.endpoint,
        context_budget=cfg.orchestrator.context_budget,
        max_retries=cfg.orchestrator.max_retries,
        journal_interval=cfg.orchestrator.journal_interval,
    )
    project_context = _build_project_context(cfg)
    llm, planner, evaluator = _build_control_plane_components(cfg)

    orchestrator = Orchestrator(
        config=orch_config,
        agents=cfg.agents,
        routing_rules=cfg.routing_rules,
        llm=llm,
        runner_factory=lambda agent_cfg: AgentRunner(agent_config=agent_cfg),
        planner=planner,
        evaluator=evaluator,
        project_context=project_context,
        skills=cfg.skills,
    )

    click.echo(run_label)
    final = asyncio.run(orchestrator.run(graph=graph, state_dir=state_dir))

    failed = [t for t in final.tasks.values() if t.status == TaskStatus.FAILED]
    escalated = [t for t in final.tasks.values() if t.status == TaskStatus.ESCALATED]
    done = [t for t in final.tasks.values() if t.status == TaskStatus.DONE]

    if verbose:
        for t in final.tasks.values():
            if t.result and t.result.output:
                click.echo(f"\n--- {t.id} output ---\n{t.result.output}")

    if failed:
        for t in failed:
            err = t.result.error if t.result else "unknown error"
            click.echo(f"Failed: {t.description}\n  {err}", err=True)
    if escalated:
        for t in escalated:
            err = t.result.error if t.result else "human intervention required"
            click.echo(f"Escalated: {t.description}\n  {err}", err=True)
    if failed or escalated:
        sys.exit(1)

    click.echo(f"Complete. {len(done)} task(s) done.")


def _build_control_plane_components(
    cfg,
) -> tuple[OllamaClient | None, Planner | None, Evaluator | None]:
    planning_enabled = cfg.orchestrator.planning_mode == "local"
    evaluation_enabled = cfg.orchestrator.evaluation_mode == "local"
    if not planning_enabled and not evaluation_enabled:
        return None, None, None

    max_tokens = 0
    if planning_enabled:
        max_tokens = max(max_tokens, cfg.orchestrator.context_budget.get("planning", 2048))
    if evaluation_enabled:
        max_tokens = max(max_tokens, cfg.orchestrator.context_budget.get("evaluation", 2048))

    llm = OllamaClient(
        model=cfg.orchestrator.model,
        endpoint=cfg.orchestrator.endpoint,
        max_tokens=max_tokens or 2048,
    )
    planner = None
    if planning_enabled:
        planner = Planner(
            llm=llm,
            context_budget=cfg.orchestrator.context_budget.get("planning", 2048),
        )

    evaluator = None
    if evaluation_enabled:
        evaluator = Evaluator(
            llm=llm,
            context_budget=cfg.orchestrator.context_budget.get("evaluation", 2048),
        )

    return llm, planner, evaluator


def _resolve_run_graph(
    task: str | None,
    resume: bool,
    state_manager: StateManager,
    agents: dict,
) -> tuple[TaskGraph, str]:
    if resume:
        graph = _load_saved_graph(state_manager)
        return graph, f"Resuming: {graph.goal}"

    _guard_existing_incomplete_state(state_manager)
    return _build_initial_graph(task=task, agents=agents), f"Running: {task}"


def _build_initial_graph(task: str | None, agents: dict) -> TaskGraph:
    session_id = str(uuid.uuid4())
    graph = TaskGraph(session_id=session_id, goal=task or "")
    first_agent = next(iter(agents)) if agents else None
    first_task = Task(id="task-0", description=task or "", agent=first_agent)
    return graph.with_task(first_task)


def _load_saved_graph(state_manager: StateManager) -> TaskGraph:
    try:
        return state_manager.load()
    except StateError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


def _guard_existing_incomplete_state(state_manager: StateManager) -> None:
    if not state_manager.has_saved_state:
        return

    try:
        graph = state_manager.load()
    except StateError as e:
        click.echo(
            f"Error: {e} Use --fresh TASK to clear the saved state and start over.",
            err=True,
        )
        sys.exit(1)

    if not graph.is_complete:
        click.echo(
            (
                f"Error: Saved session '{graph.goal}' is still in progress. "
                "Use --resume to continue it or --fresh TASK to start over."
            ),
            err=True,
        )
        sys.exit(1)


def _build_project_context(cfg) -> str | None:
    parts = []

    if cfg.project is not None:
        project = cfg.project
        parts.append(f"Project: {project.name}")
        parts.append(f"Description: {project.description}")
        if project.tech_stack:
            parts.append(f"Tech stack: {', '.join(project.tech_stack)}")
        if project.conventions:
            parts.append(f"Conventions:\n{project.conventions}")
        if project.test_command:
            parts.append(f"Test command: {project.test_command}")
        if project.build_command:
            parts.append(f"Build command: {project.build_command}")
        if project.orchestrator_context:
            parts.append(f"Orchestrator context:\n{project.orchestrator_context}")

    if cfg.agents:
        agent_lines = []
        for name, agent in cfg.agents.items():
            strengths = ", ".join(agent.strengths) if agent.strengths else "unspecified"
            agent_lines.append(f"- {name}: {agent.description} (strengths: {strengths})")
        parts.append("Available agents:\n" + "\n".join(agent_lines))

    if cfg.skills:
        skill_lines = []
        for name, skill in cfg.skills.items():
            use_when = ", ".join(skill.use_when) if skill.use_when else "general"
            skill_lines.append(f"- {name}: invoke {skill.invoke} via {skill.agent} for {use_when}")
        parts.append("Available skills:\n" + "\n".join(skill_lines))

    return "\n\n".join(parts) if parts else None


@cli.group()
@click.pass_context
def config(ctx: click.Context):
    """Manage Ralph configuration."""


@config.command("show")
@click.pass_context
def config_show(ctx: click.Context):
    """Print the resolved (merged) configuration."""
    config_path = ctx.obj.get("config_path")
    project_dir = ctx.obj.get("project_dir", Path.cwd())

    with warnings.catch_warnings(record=True):
        warnings.simplefilter("always")
        try:
            cfg = load_config(global_config_path=config_path, project_dir=project_dir)
        except ConfigError as e:
            click.echo(f"Error: {e}", err=True)
            sys.exit(1)

    click.echo(yaml.dump(cfg.model_dump(), default_flow_style=False, sort_keys=False))


@config.command("validate")
@click.pass_context
def config_validate(ctx: click.Context):
    """Validate global and project configs and report any issues."""
    config_path = ctx.obj.get("config_path")
    project_dir = ctx.obj.get("project_dir", Path.cwd())

    caught_warnings = []
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        try:
            load_config(global_config_path=config_path, project_dir=project_dir)
            caught_warnings = list(w)
        except ConfigError as e:
            click.echo(f"Invalid: {e}", err=True)
            sys.exit(1)

    if caught_warnings:
        for warning in caught_warnings:
            click.echo(f"Warning: {warning.message}", err=True)

    click.echo("Config is valid.")


@config.command("init")
def config_init():
    """Generate a starter ~/.ralph/config.yaml."""
    ralph_dir = Path.home() / ".ralph"
    ralph_dir.mkdir(exist_ok=True)
    dest = ralph_dir / "config.yaml"

    example = Path(__file__).parent.parent.parent / "config.yaml.example"
    if example.exists():
        dest.write_text(example.read_text())
        click.echo(f"Created {dest}")
    else:
        click.echo(f"Error: config.yaml.example not found at {example}", err=True)
        sys.exit(1)


@config.command("init-project")
@click.option("--project-dir", type=click.Path(path_type=Path), default=None)
def config_init_project(project_dir):
    """Generate a starter .ralph/project.yaml in the current (or specified) directory."""
    if project_dir is None:
        project_dir = Path.cwd()

    ralph_dir = Path(project_dir) / ".ralph"
    ralph_dir.mkdir(exist_ok=True)
    dest = ralph_dir / "project.yaml"

    if dest.exists():
        click.echo(f"{dest} already exists — not overwriting.")
        return

    dest.write_text("""\
project:
  name: MyProject
  description: "Brief project description"
  tech_stack: []        # e.g. ["python", "fastapi"]
  conventions: |
    # Add project-specific conventions here.
    # Ralph reads these on every session to stay oriented.
  test_command: ""      # e.g. "pytest"
  build_command: ""     # e.g. "make build"

  # Override global routing rules for this project
  routing_overrides: []
  # Example:
  # routing_overrides:
  #   - task_type: implementation
  #     prefer: claude_code
  #     reason: "Project needs stronger reasoning"

  # Extra context injected into Ralph's system prompt for this project
  orchestrator_context: |
    # Add project-specific guidance for the orchestrator here.
""")
    click.echo(f"Created {dest}")
