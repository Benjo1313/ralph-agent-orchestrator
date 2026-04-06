"""Pydantic models for Ralph's two-tier configuration system."""
from typing import Literal

from pydantic import BaseModel, field_validator


class OrchestratorConfig(BaseModel):
    model: str
    provider: str
    endpoint: str
    context_budget: dict[str, int] = {
        "planning": 4096,
        "routing": 2048,
        "evaluation": 3072,
        "retry": 2048,
    }
    re_anchor_interval: int = 5
    max_retries: int = 3
    journal_interval: str | int = "session_end"


class AgentConfig(BaseModel):
    type: Literal["cli", "api"]
    description: str
    strengths: list[str] = []
    # CLI fields
    command: str | None = None
    flags: list[str] = []
    # API fields
    provider: str | None = None
    model: str | None = None

    @field_validator("type")
    @classmethod
    def validate_type(cls, v: str) -> str:
        if v not in ("cli", "api"):
            raise ValueError(f"Agent type must be 'cli' or 'api', got '{v}'")
        return v


class RoutingRule(BaseModel):
    task_type: str
    prefer: str
    when: str | None = None
    reason: str | None = None


class SkillConfig(BaseModel):
    agent: str
    invoke: str
    use_when: list[str] = []


class ProjectConfig(BaseModel):
    name: str
    description: str
    tech_stack: list[str] = []
    conventions: str | None = None
    test_command: str | None = None
    build_command: str | None = None
    routing_overrides: list[RoutingRule] = []
    orchestrator_context: str | None = None


class RalphConfig(BaseModel):
    orchestrator: OrchestratorConfig
    agents: dict[str, AgentConfig]
    routing_rules: list[RoutingRule]
    skills: dict[str, SkillConfig]
    project: ProjectConfig | None = None
