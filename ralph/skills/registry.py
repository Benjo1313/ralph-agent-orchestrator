"""SkillRegistry: lookup and resolution of pre-prompted agent skills."""
from dataclasses import dataclass

from ralph.config.schema import AgentConfig, SkillConfig


@dataclass
class ResolvedSkill:
    name: str
    skill: SkillConfig
    agent_config: AgentConfig

    @property
    def invoke(self) -> str:
        return self.skill.invoke


class SkillRegistry:
    def __init__(self, agents: dict[str, AgentConfig], skills: dict[str, SkillConfig]) -> None:
        self.agents = agents
        self.skills = skills

    def get(self, name: str) -> ResolvedSkill | None:
        skill = self.skills.get(name)
        if skill is None:
            return None
        agent_config = self.agents.get(skill.agent)
        if agent_config is None:
            return None
        return ResolvedSkill(name=name, skill=skill, agent_config=agent_config)

    def skills_for(self, use_case: str) -> list[ResolvedSkill]:
        matched = []
        for name, skill in self.skills.items():
            if use_case in skill.use_when:
                resolved = self.get(name)
                if resolved is not None:
                    matched.append(resolved)
        return matched

    def list_all(self) -> list[ResolvedSkill]:
        result = []
        for name in self.skills:
            resolved = self.get(name)
            if resolved is not None:
                result.append(resolved)
        return result
