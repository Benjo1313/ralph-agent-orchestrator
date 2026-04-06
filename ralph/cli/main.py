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
from ralph.core.orchestrator import Orchestrator
from ralph.core.orchestrator import OrchestratorConfig as OrchestratorRunConfig
from ralph.core.task_graph import Task, TaskGraph, TaskStatus
from ralph.llm.ollama_client import OllamaClient
from ralph.memory.state import StateManager


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
@click.argument("task")
@click.option("--dry-run", is_flag=True, default=False, help="Plan and route without dispatching agents.")
@click.option("--resume", is_flag=True, default=False, help="Resume previous session automatically.")
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

    if fresh and state_manager.has_saved_state:
        state_manager.clear()
        click.echo("Cleared previous session state.")

    llm = OllamaClient(
        model=cfg.orchestrator.model,
        endpoint=cfg.orchestrator.endpoint,
        max_tokens=cfg.orchestrator.context_budget.get("planning", 2048),
    )

    orch_config = OrchestratorRunConfig(
        model=cfg.orchestrator.model,
        endpoint=cfg.orchestrator.endpoint,
        context_budget=cfg.orchestrator.context_budget,
        max_retries=cfg.orchestrator.max_retries,
    )

    orchestrator = Orchestrator(
        config=orch_config,
        agents=cfg.agents,
        routing_rules=cfg.routing_rules,
        llm=llm,
        runner_factory=lambda agent_cfg: AgentRunner(agent_config=agent_cfg),
    )

    # Build a single-task graph from the user's task string
    session_id = str(uuid.uuid4())
    graph = TaskGraph(session_id=session_id, goal=task)
    first_agent = next(iter(cfg.agents)) if cfg.agents else None
    t = Task(id="task-0", description=task, agent=first_agent)
    graph = graph.with_task(t)

    click.echo(f"Running: {task}")
    final = asyncio.run(orchestrator.run(graph=graph, state_dir=state_dir))

    failed = [t for t in final.tasks.values() if t.status == TaskStatus.FAILED]
    done = [t for t in final.tasks.values() if t.status == TaskStatus.DONE]

    if verbose:
        for t in final.tasks.values():
            if t.result and t.result.output:
                click.echo(f"\n--- {t.id} output ---\n{t.result.output}")

    if failed:
        for t in failed:
            err = t.result.error if t.result else "unknown error"
            click.echo(f"Failed: {t.description}\n  {err}", err=True)
        sys.exit(1)

    click.echo(f"Complete. {len(done)} task(s) done.")


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
