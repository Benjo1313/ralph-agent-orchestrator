"""AgentRunner: dispatches tasks to CLI or API agents."""
import asyncio
from dataclasses import dataclass

from ralph.config.schema import AgentConfig


@dataclass
class RunResult:
    success: bool
    output: str | None = None
    error: str | None = None


class AgentRunner:
    def __init__(self, agent_config: AgentConfig) -> None:
        self.config = agent_config

    async def run(self, prompt: str) -> RunResult:
        if self.config.type == "cli":
            return await self._run_cli(prompt)
        else:
            return await self._run_api(prompt)

    async def _run_cli(self, prompt: str) -> RunResult:
        cmd = self.config.command
        args = [cmd] + list(self.config.flags) + [prompt]
        try:
            proc = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
        except Exception as e:
            return RunResult(success=False, error=str(e))

        if proc.returncode != 0:
            stderr_text = stderr.decode(errors="replace")
            return RunResult(
                success=False,
                error=f"Agent exited with code {proc.returncode}. stderr: {stderr_text}",
            )

        return RunResult(success=True, output=stdout.decode(errors="replace"))

    async def _run_api(self, prompt: str) -> RunResult:
        provider = self.config.provider or "unknown"
        return RunResult(
            success=False,
            error=f"API provider '{provider}' is not yet supported. Add it to ralph/agents/runner.py.",
        )
