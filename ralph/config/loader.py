"""Two-tier YAML config loading: global + per-project."""
import warnings
from pathlib import Path

import yaml
from pydantic import ValidationError

from ralph.config.schema import AgentConfig, OrchestratorConfig, ProjectConfig, RalphConfig, RoutingRule, SkillConfig


class ConfigError(Exception):
    pass


def load_config(
    global_config_path: Path | None = None,
    project_dir: Path | None = None,
) -> RalphConfig:
    if global_config_path is None:
        global_config_path = Path.home() / ".ralph" / "config.yaml"
    if project_dir is None:
        project_dir = Path.cwd()

    if not global_config_path.exists():
        raise ConfigError(
            f"Global config not found at {global_config_path}.\n"
            "Run 'ralph config init' to create a starter config."
        )

    try:
        raw = yaml.safe_load(global_config_path.read_text())
    except yaml.YAMLError as e:
        raise ConfigError(f"Failed to parse global config at {global_config_path}: {e}") from e

    if not isinstance(raw, dict):
        raise ConfigError(f"Global config at {global_config_path} is not a valid YAML mapping.")

    try:
        orchestrator = OrchestratorConfig(**raw.get("orchestrator", {}))
    except (ValidationError, TypeError) as e:
        raise ConfigError(f"Invalid orchestrator config in {global_config_path}:\n{e}") from e

    agents: dict[str, AgentConfig] = {}
    for name, agent_data in raw.get("agents", {}).items():
        try:
            agents[name] = AgentConfig(**agent_data)
        except (ValidationError, TypeError) as e:
            raise ConfigError(f"Invalid agent '{name}' in {global_config_path}:\n{e}") from e

    routing_rules: list[RoutingRule] = []
    for rule_data in raw.get("routing", {}).get("rules", []):
        try:
            routing_rules.append(RoutingRule(**rule_data))
        except (ValidationError, TypeError) as e:
            raise ConfigError(f"Invalid routing rule in {global_config_path}:\n{e}") from e

    skills: dict[str, SkillConfig] = {}
    for name, skill_data in raw.get("skills", {}).items():
        try:
            skills[name] = SkillConfig(**skill_data)
        except (ValidationError, TypeError) as e:
            raise ConfigError(f"Invalid skill '{name}' in {global_config_path}:\n{e}") from e

    project: ProjectConfig | None = None
    project_config_path = Path(project_dir) / ".ralph" / "project.yaml"
    if project_config_path.exists():
        try:
            project_raw = yaml.safe_load(project_config_path.read_text())
            project_data = project_raw.get("project", {}) if isinstance(project_raw, dict) else {}
            project = ProjectConfig(**project_data)
            # Merge project routing overrides into global rules
            routing_rules = routing_rules + project.routing_overrides
        except yaml.YAMLError as e:
            warnings.warn(f"Failed to parse project config at {project_config_path}: {e}")
        except (ValidationError, TypeError) as e:
            warnings.warn(f"Invalid project config at {project_config_path}: {e}")
    else:
        warnings.warn(
            f"No project config found at {project_config_path}. "
            "Using global config only. Run 'ralph config init-project' to create one."
        )

    return RalphConfig(
        orchestrator=orchestrator,
        agents=agents,
        routing_rules=routing_rules,
        skills=skills,
        project=project,
    )
