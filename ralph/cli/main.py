"""Ralph CLI entry point."""
import sys
import warnings
from pathlib import Path

import click
import yaml

from ralph.config.loader import ConfigError, load_config


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
            load_config(global_config_path=config_path, project_dir=project_dir)
        except ConfigError as e:
            click.echo(f"Error: {e}", err=True)
            sys.exit(1)

    if dry_run:
        click.echo(f"[DRY RUN] Task: {task}")
        click.echo("(Dispatch skipped — dry-run mode)")
    else:
        click.echo(f"Task: {task}")
        click.echo("(Orchestration loop not yet implemented — Phase 5)")


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
