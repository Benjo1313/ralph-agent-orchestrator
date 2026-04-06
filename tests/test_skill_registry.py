"""Tests for SkillRegistry — lookup and resolution of pre-prompted agent skills."""
import pytest

from ralph.skills.registry import SkillRegistry, ResolvedSkill
from ralph.config.schema import AgentConfig, SkillConfig


@pytest.fixture
def agents():
    return {
        "claude_code": AgentConfig(
            type="cli",
            command="claude",
            flags=["--print"],
            description="Claude Code",
            strengths=["architecture"],
        ),
    }


@pytest.fixture
def skills():
    return {
        "tdd": SkillConfig(
            agent="claude_code",
            invoke="/tdd",
            use_when=["test_writing", "implementation_with_tests"],
        ),
        "code_review": SkillConfig(
            agent="claude_code",
            invoke="/review-pr",
            use_when=["code_review"],
        ),
    }


@pytest.fixture
def registry(agents, skills):
    return SkillRegistry(agents=agents, skills=skills)


class TestResolvedSkill:
    def test_fields(self):
        agent_cfg = AgentConfig(type="cli", command="claude", flags=[], description="x", strengths=[])
        skill_cfg = SkillConfig(agent="claude_code", invoke="/tdd", use_when=[])
        r = ResolvedSkill(name="tdd", skill=skill_cfg, agent_config=agent_cfg)
        assert r.name == "tdd"
        assert r.invoke == "/tdd"
        assert r.agent_config.command == "claude"


class TestSkillRegistry:
    def test_get_existing_skill(self, registry):
        resolved = registry.get("tdd")
        assert resolved is not None
        assert resolved.name == "tdd"
        assert resolved.invoke == "/tdd"
        assert resolved.agent_config.command == "claude"

    def test_get_missing_skill_returns_none(self, registry):
        assert registry.get("nonexistent") is None

    def test_get_skill_with_missing_agent_returns_none(self, skills):
        agents_without_claude = {}
        registry = SkillRegistry(agents=agents_without_claude, skills=skills)
        assert registry.get("tdd") is None

    def test_skills_for_use_case_returns_matching(self, registry):
        matched = registry.skills_for("test_writing")
        assert len(matched) == 1
        assert matched[0].name == "tdd"

    def test_skills_for_use_case_returns_multiple(self, registry):
        # code_review use_when contains "code_review"
        matched = registry.skills_for("code_review")
        assert any(s.name == "code_review" for s in matched)

    def test_skills_for_unknown_use_case_returns_empty(self, registry):
        assert registry.skills_for("deployment") == []

    def test_list_all_returns_all_valid(self, registry):
        all_skills = registry.list_all()
        names = {s.name for s in all_skills}
        assert names == {"tdd", "code_review"}

    def test_empty_registry(self):
        registry = SkillRegistry(agents={}, skills={})
        assert registry.list_all() == []
        assert registry.get("tdd") is None
        assert registry.skills_for("test_writing") == []
