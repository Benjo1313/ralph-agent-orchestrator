"""Tests for CLI entry point and config subcommands."""
import textwrap
from pathlib import Path

import pytest
from click.testing import CliRunner

from ralph.cli.main import cli


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def global_config(tmp_path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text(textwrap.dedent("""\
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
        routing:
          rules:
            - task_type: architecture
              prefer: claude_code
        skills: {}
    """))
    return cfg


class TestCLIEntryPoint:
    def test_help(self, runner):
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "ralph" in result.output.lower()

    def test_version(self, runner):
        result = runner.invoke(cli, ["--version"])
        assert result.exit_code == 0

    def test_task_echoed(self, runner, global_config, tmp_path):
        result = runner.invoke(
            cli,
            ["--config", str(global_config), "--project-dir", str(tmp_path), "run", "--dry-run", "add dark mode toggle"],
        )
        assert result.exit_code == 0
        assert "add dark mode toggle" in result.output


class TestConfigSubcommands:
    def test_config_show(self, runner, global_config, tmp_path):
        result = runner.invoke(
            cli,
            ["--config", str(global_config), "--project-dir", str(tmp_path), "config", "show"],
        )
        assert result.exit_code == 0
        assert "gemma4:27b" in result.output

    def test_config_validate_valid(self, runner, global_config, tmp_path):
        result = runner.invoke(
            cli,
            ["--config", str(global_config), "--project-dir", str(tmp_path), "config", "validate"],
        )
        assert result.exit_code == 0
        assert "valid" in result.output.lower()

    def test_config_validate_missing(self, runner, tmp_path):
        result = runner.invoke(
            cli,
            ["--config", str(tmp_path / "missing.yaml"), "--project-dir", str(tmp_path), "config", "validate"],
        )
        assert result.exit_code != 0

    def test_config_init_project(self, runner, tmp_path):
        result = runner.invoke(cli, ["config", "init-project", "--project-dir", str(tmp_path)])
        assert result.exit_code == 0
        assert (tmp_path / ".ralph" / "project.yaml").exists()
