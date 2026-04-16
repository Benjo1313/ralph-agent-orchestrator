"""Tests for config schema validation and loader."""
import textwrap

import pytest
from pydantic import ValidationError

from ralph.config.loader import ConfigError, load_config
from ralph.config.schema import (
    AgentConfig,
    OrchestratorConfig,
    ProjectConfig,
    RalphConfig,
    RoutingRule,
    SkillConfig,
)

# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------


class TestOrchestratorConfig:
    def test_valid(self):
        cfg = OrchestratorConfig(
            model="gemma4:27b",
            provider="ollama",
            endpoint="http://localhost:11434",
        )
        assert cfg.model == "gemma4:27b"
        assert cfg.max_retries == 3  # default

    def test_defaults(self):
        cfg = OrchestratorConfig(
            model="gemma4:27b", provider="ollama", endpoint="http://localhost:11434"
        )
        assert cfg.re_anchor_interval == 5
        assert cfg.journal_interval == "session_end"
        assert cfg.context_budget["planning"] == 4096

    def test_missing_required_fields(self):
        with pytest.raises(ValidationError, match="Local control-plane mode"):
            OrchestratorConfig()

    def test_allows_disabled_control_plane_without_model_fields(self):
        cfg = OrchestratorConfig(
            planning_mode="disabled",
            evaluation_mode="disabled",
        )
        assert cfg.model is None
        assert cfg.endpoint is None

    def test_requires_model_fields_when_evaluation_stays_local(self):
        with pytest.raises(ValidationError, match="Local control-plane mode for evaluation"):
            OrchestratorConfig(
                planning_mode="disabled",
                evaluation_mode="local",
            )

    def test_accepts_positive_integer_journal_interval(self):
        cfg = OrchestratorConfig(
            model="gemma4:27b",
            provider="ollama",
            endpoint="http://localhost:11434",
            journal_interval=2,
        )
        assert cfg.journal_interval == 2

    def test_rejects_invalid_journal_interval_string(self):
        with pytest.raises(ValidationError):
            OrchestratorConfig(
                model="gemma4:27b",
                provider="ollama",
                endpoint="http://localhost:11434",
                journal_interval="sometimes",
            )

    def test_rejects_non_positive_integer_journal_interval(self):
        with pytest.raises(ValidationError):
            OrchestratorConfig(
                model="gemma4:27b",
                provider="ollama",
                endpoint="http://localhost:11434",
                journal_interval=0,
            )


class TestAgentConfig:
    def test_cli_agent(self):
        agent = AgentConfig(
            type="cli",
            command="claude",
            flags=["--print"],
            description="Claude Code",
            strengths=["architecture"],
        )
        assert agent.type == "cli"
        assert agent.command == "claude"

    def test_cli_agent_defaults_to_argument_prompt_mode(self):
        agent = AgentConfig(
            type="cli",
            command="claude",
            description="Claude Code",
        )
        assert agent.prompt_mode == "argument"

    def test_cli_agent_accepts_stdin_prompt_mode(self):
        agent = AgentConfig(
            type="cli",
            command="claude",
            prompt_mode="stdin",
            description="Claude Code",
        )
        assert agent.prompt_mode == "stdin"

    def test_api_agent(self):
        agent = AgentConfig(
            type="api",
            provider="anthropic",
            model="claude-sonnet-4-6",
            description="Claude API",
            strengths=["code_review"],
        )
        assert agent.type == "api"
        assert agent.provider == "anthropic"

    def test_invalid_type(self):
        with pytest.raises(ValidationError):
            AgentConfig(type="invalid", description="bad")

    def test_cli_agent_requires_command(self):
        with pytest.raises(ValidationError, match="CLI agents require a command"):
            AgentConfig(type="cli", description="bad")

    def test_cli_agent_rejects_api_fields(self):
        with pytest.raises(ValidationError, match="CLI agents cannot define API fields"):
            AgentConfig(
                type="cli",
                command="claude",
                provider="openai",
                model="gpt-5",
                description="bad",
            )

    def test_api_agent_requires_provider_and_model(self):
        with pytest.raises(ValidationError, match="API agents require both provider and model"):
            AgentConfig(type="api", description="bad")

    def test_api_agent_rejects_command(self):
        with pytest.raises(ValidationError, match="API agents cannot define a CLI command"):
            AgentConfig(
                type="api",
                provider="openai",
                model="gpt-5",
                command="codex",
                description="bad",
            )


class TestRoutingRule:
    def test_basic(self):
        rule = RoutingRule(task_type="architecture", prefer="claude_code")
        assert rule.task_type == "architecture"
        assert rule.prefer == "claude_code"
        assert rule.when is None
        assert rule.reason is None

    def test_with_condition(self):
        rule = RoutingRule(
            task_type="implementation",
            prefer="codex",
            when="complexity < medium",
            reason="Fast for simple tasks",
        )
        assert rule.when == "complexity < medium"


class TestSkillConfig:
    def test_valid(self):
        skill = SkillConfig(
            agent="claude_code",
            invoke="/tdd",
            use_when=["test_writing", "implementation_with_tests"],
        )
        assert skill.invoke == "/tdd"
        assert "test_writing" in skill.use_when


class TestProjectConfig:
    def test_minimal(self):
        project = ProjectConfig(name="MyProject", description="A project")
        assert project.name == "MyProject"
        assert project.routing_overrides == []
        assert project.orchestrator_context is None

    def test_full(self):
        project = ProjectConfig(
            name="GetReady",
            description="iOS app",
            tech_stack=["swift", "swiftui"],
            conventions="Swift 6, strict concurrency.",
            test_command="xcodebuild test ...",
            build_command="xcodegen generate",
            orchestrator_context="Always run xcodegen after file changes.",
        )
        assert project.tech_stack == ["swift", "swiftui"]


class TestRalphConfig:
    def test_requires_orchestrator(self):
        with pytest.raises(ValidationError):
            RalphConfig(agents={}, routing_rules=[], skills={})


# ---------------------------------------------------------------------------
# Loader tests
# ---------------------------------------------------------------------------


@pytest.fixture
def global_config_yaml():
    return textwrap.dedent("""\
        orchestrator:
          model: gemma4:27b
          provider: ollama
          endpoint: http://localhost:11434

        agents:
          claude_code:
            type: cli
            command: claude
            flags: ["--print"]
            description: "Claude Code"
            strengths: ["architecture"]
          claude_api:
            type: api
            provider: anthropic
            model: claude-sonnet-4-6
            description: "Claude API"
            strengths: ["code_review"]

        routing:
          rules:
            - task_type: architecture
              prefer: claude_code
              reason: "Complex tasks"
            - task_type: code_review
              prefer: claude_api

        skills:
          tdd:
            agent: claude_code
            invoke: "/tdd"
            use_when: ["test_writing"]
    """)


@pytest.fixture
def project_config_yaml():
    return textwrap.dedent("""\
        project:
          name: GetReady
          description: "iOS app"
          tech_stack: ["swift"]
          conventions: "Swift 6"
          test_command: "xcodebuild test"
          routing_overrides:
            - task_type: implementation
              prefer: claude_code
              reason: "Swift needs Claude"
          orchestrator_context: "Always run xcodegen."
    """)


class TestLoadConfig:
    def test_global_only(self, tmp_path, global_config_yaml):
        global_cfg = tmp_path / "config.yaml"
        global_cfg.write_text(global_config_yaml)

        config = load_config(global_config_path=global_cfg, project_dir=tmp_path / "no_project")
        assert config.orchestrator.model == "gemma4:27b"
        assert "claude_code" in config.agents
        assert config.project is None

    def test_global_and_project(self, tmp_path, global_config_yaml, project_config_yaml):
        global_cfg = tmp_path / "config.yaml"
        global_cfg.write_text(global_config_yaml)

        project_dir = tmp_path / "myproject"
        project_dir.mkdir()
        ralph_dir = project_dir / ".ralph"
        ralph_dir.mkdir()
        (ralph_dir / "project.yaml").write_text(project_config_yaml)

        config = load_config(global_config_path=global_cfg, project_dir=project_dir)
        assert config.project is not None
        assert config.project.name == "GetReady"

    def test_project_routing_overrides_merge(
        self,
        tmp_path,
        global_config_yaml,
        project_config_yaml,
    ):
        global_cfg = tmp_path / "config.yaml"
        global_cfg.write_text(global_config_yaml)

        project_dir = tmp_path / "myproject"
        project_dir.mkdir()
        ralph_dir = project_dir / ".ralph"
        ralph_dir.mkdir()
        (ralph_dir / "project.yaml").write_text(project_config_yaml)

        config = load_config(global_config_path=global_cfg, project_dir=project_dir)
        # Project override adds an implementation rule
        impl_rules = [r for r in config.routing_rules if r.task_type == "implementation"]
        assert len(impl_rules) == 1
        assert impl_rules[0].prefer == "claude_code"

    def test_missing_global_config_raises(self, tmp_path):
        with pytest.raises(ConfigError, match="Global config not found"):
            load_config(
                global_config_path=tmp_path / "nonexistent.yaml",
                project_dir=tmp_path,
            )

    def test_missing_project_config_returns_none_project(self, tmp_path, global_config_yaml):
        global_cfg = tmp_path / "config.yaml"
        global_cfg.write_text(global_config_yaml)

        config = load_config(global_config_path=global_cfg, project_dir=tmp_path / "empty")
        assert config.project is None

    def test_disabled_control_plane_can_omit_ollama_fields(self, tmp_path):
        global_cfg = tmp_path / "config.yaml"
        global_cfg.write_text(
            textwrap.dedent(
                """\
                orchestrator:
                  planning_mode: disabled
                  evaluation_mode: disabled

                agents:
                  claude_code:
                    type: cli
                    command: claude
                    description: "Claude Code"

                routing:
                  rules: []

                skills: {}
                """
            )
        )

        config = load_config(global_config_path=global_cfg, project_dir=tmp_path)
        assert config.orchestrator.planning_mode == "disabled"
        assert config.orchestrator.evaluation_mode == "disabled"
        assert config.orchestrator.model is None

    def test_invalid_global_config_raises(self, tmp_path):
        global_cfg = tmp_path / "config.yaml"
        global_cfg.write_text("orchestrator:\n  model: 123\n  provider: []\n")
        with pytest.raises(ConfigError):
            load_config(global_config_path=global_cfg, project_dir=tmp_path)
