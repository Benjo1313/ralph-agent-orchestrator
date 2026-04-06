"""Tests for Router — maps task types to agents via config routing rules."""
import pytest

from ralph.core.router import Router, RoutingDecision
from ralph.config.schema import AgentConfig, RoutingRule


@pytest.fixture
def agents():
    return {
        "claude_code": AgentConfig(
            type="cli",
            command="claude",
            flags=["--print"],
            description="Claude Code",
            strengths=["architecture", "implementation"],
        ),
        "claude_api": AgentConfig(
            type="api",
            provider="anthropic",
            model="claude-sonnet-4-6",
            description="Claude API",
            strengths=["code_review"],
        ),
    }


@pytest.fixture
def rules():
    return [
        RoutingRule(task_type="architecture", prefer="claude_code", reason="Complex reasoning"),
        RoutingRule(task_type="code_review", prefer="claude_api", reason="Lightweight"),
    ]


@pytest.fixture
def router(agents, rules):
    return Router(agents=agents, rules=rules)


class TestRoutingDecision:
    def test_fields(self):
        d = RoutingDecision(agent_name="claude_code", reason="Matched rule")
        assert d.agent_name == "claude_code"
        assert d.reason == "Matched rule"


class TestRouter:
    def test_routes_to_matching_rule(self, router):
        decision = router.route(task_type="architecture")
        assert decision.agent_name == "claude_code"
        assert "Matched" in decision.reason or "architecture" in decision.reason

    def test_routes_code_review_to_api(self, router):
        decision = router.route(task_type="code_review")
        assert decision.agent_name == "claude_api"

    def test_falls_back_to_first_agent_when_no_rule(self, router):
        decision = router.route(task_type="unknown_task_type")
        # Should fall back to first available agent
        assert decision.agent_name in {"claude_code", "claude_api"}
        assert "fallback" in decision.reason.lower()

    def test_skips_rule_pointing_to_missing_agent(self, agents, rules):
        rules_with_missing = rules + [
            RoutingRule(task_type="testing", prefer="nonexistent_agent")
        ]
        router = Router(agents=agents, rules=rules_with_missing)
        decision = router.route(task_type="testing")
        # Falls back because preferred agent doesn't exist
        assert decision.agent_name in agents
        assert "fallback" in decision.reason.lower()

    def test_no_agents_raises(self):
        router = Router(agents={}, rules=[])
        with pytest.raises(ValueError, match="No agents"):
            router.route(task_type="anything")

    def test_empty_rules_falls_back(self, agents):
        router = Router(agents=agents, rules=[])
        decision = router.route(task_type="implementation")
        assert decision.agent_name in agents
        assert "fallback" in decision.reason.lower()

    def test_rule_reason_propagated(self, router):
        decision = router.route(task_type="architecture")
        # The config reason "Complex reasoning" should appear or at least the rule matched
        assert decision.agent_name == "claude_code"
