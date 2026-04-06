"""Router: maps task types to agents using configured routing rules."""
from dataclasses import dataclass

from ralph.config.schema import AgentConfig, RoutingRule


@dataclass
class RoutingDecision:
    agent_name: str
    reason: str


class Router:
    def __init__(self, agents: dict[str, AgentConfig], rules: list[RoutingRule]) -> None:
        self.agents = agents
        self.rules = rules

    def route(self, task_type: str) -> RoutingDecision:
        if not self.agents:
            raise ValueError("No agents configured.")

        for rule in self.rules:
            if rule.task_type == task_type and rule.prefer in self.agents:
                reason = f"Matched rule for '{task_type}'"
                if rule.reason:
                    reason = f"{reason}: {rule.reason}"
                return RoutingDecision(agent_name=rule.prefer, reason=reason)

        first = next(iter(self.agents))
        return RoutingDecision(
            agent_name=first,
            reason=f"No matching rule for '{task_type}' — fallback to first configured agent",
        )
