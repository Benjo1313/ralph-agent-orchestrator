"""Pydantic models for Ralph's two-tier configuration system."""
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class OrchestratorConfig(BaseModel):
    model: str | None = None
    provider: str | None = None
    endpoint: str | None = None
    planning_mode: Literal["local", "disabled"] = "local"
    evaluation_mode: Literal["local", "disabled"] = "local"
    context_budget: dict[str, int] = Field(
        default_factory=lambda: {
            "planning": 4096,
            "routing": 2048,
            "evaluation": 3072,
            "retry": 2048,
        }
    )
    re_anchor_interval: int = 5
    max_retries: int = 3
    journal_interval: str | int = "session_end"

    @field_validator("journal_interval")
    @classmethod
    def validate_journal_interval(cls, value: str | int) -> str | int:
        if isinstance(value, str):
            if value != "session_end":
                raise ValueError("journal_interval must be 'session_end' or a positive integer")
            return value
        if value <= 0:
            raise ValueError("journal_interval must be 'session_end' or a positive integer")
        return value

    @model_validator(mode="after")
    def validate_control_plane_requirements(self) -> "OrchestratorConfig":
        uses_local_control_plane = (
            self.planning_mode == "local" or self.evaluation_mode == "local"
        )
        if not uses_local_control_plane:
            return self

        missing_fields: list[str] = []
        if not self.model:
            missing_fields.append("model")
        if not self.provider:
            missing_fields.append("provider")
        if not self.endpoint:
            missing_fields.append("endpoint")

        if missing_fields:
            stages = []
            if self.planning_mode == "local":
                stages.append("planning")
            if self.evaluation_mode == "local":
                stages.append("evaluation")
            stage_list = " and ".join(stages)
            missing_list = ", ".join(missing_fields)
            raise ValueError(
                f"Local control-plane mode for {stage_list} requires orchestrator "
                f"{missing_list}."
            )
        return self


class AgentConfig(BaseModel):
    type: Literal["cli", "api"]
    description: str
    strengths: list[str] = Field(default_factory=list)
    # CLI fields
    command: str | None = None
    flags: list[str] = Field(default_factory=list)
    prompt_mode: Literal["argument", "stdin"] = "argument"
    # API fields
    provider: str | None = None
    model: str | None = None

    @field_validator("type")
    @classmethod
    def validate_type(cls, v: str) -> str:
        if v not in ("cli", "api"):
            raise ValueError(f"Agent type must be 'cli' or 'api', got '{v}'")
        return v

    @model_validator(mode="after")
    def validate_agent_shape(self) -> "AgentConfig":
        if self.type == "cli":
            if not self.command:
                raise ValueError("CLI agents require a command.")
            if self.provider is not None or self.model is not None:
                raise ValueError("CLI agents cannot define API fields (provider/model).")
            return self

        if not self.provider or not self.model:
            raise ValueError("API agents require both provider and model.")
        if self.command is not None:
            raise ValueError("API agents cannot define a CLI command.")
        return self


class RoutingRule(BaseModel):
    task_type: str
    prefer: str
    when: str | None = None
    reason: str | None = None


class SkillConfig(BaseModel):
    agent: str
    invoke: str
    use_when: list[str] = Field(default_factory=list)


class ProjectConfig(BaseModel):
    name: str
    description: str
    tech_stack: list[str] = Field(default_factory=list)
    conventions: str | None = None
    test_command: str | None = None
    build_command: str | None = None
    routing_overrides: list[RoutingRule] = Field(default_factory=list)
    orchestrator_context: str | None = None


class RalphConfig(BaseModel):
    orchestrator: OrchestratorConfig
    agents: dict[str, AgentConfig]
    routing_rules: list[RoutingRule]
    skills: dict[str, SkillConfig]
    project: ProjectConfig | None = None
