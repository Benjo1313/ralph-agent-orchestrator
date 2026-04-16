"""AgentRunner: dispatches tasks to CLI or API agents."""
import asyncio
import os
from dataclasses import dataclass

from ralph.config.schema import AgentConfig

try:
    from anthropic import AsyncAnthropic
except ImportError:  # pragma: no cover - exercised via failure handling
    AsyncAnthropic = None

try:
    from openai import AsyncOpenAI
except ImportError:  # pragma: no cover - exercised via failure handling
    AsyncOpenAI = None


@dataclass
class RunResult:
    success: bool
    output: str | None = None
    error: str | None = None
    exit_code: int | None = None


class AgentRunner:
    def __init__(self, agent_config: AgentConfig) -> None:
        self.config = agent_config

    async def run(self, prompt: str, system_message: str | None = None) -> RunResult:
        if self.config.type == "cli":
            return await self._run_cli(prompt)
        else:
            return await self._run_api(prompt, system_message=system_message)

    async def _run_cli(self, prompt: str) -> RunResult:
        cmd = self.config.command
        if cmd is None:
            return RunResult(success=False, error="CLI agent is missing a command.")

        args = [cmd] + list(self.config.flags)
        stdin = None
        stdin_payload = None
        if self.config.prompt_mode == "stdin":
            stdin = asyncio.subprocess.PIPE
            stdin_payload = prompt.encode()
        else:
            args.append(prompt)

        try:
            proc = await asyncio.create_subprocess_exec(
                *args,
                stdin=stdin,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate(stdin_payload)
        except FileNotFoundError:
            return RunResult(
                success=False,
                error=(
                    f"CLI agent command '{cmd}' was not found on PATH. "
                    "Install it or update the agent command in your Ralph config."
                ),
            )
        except Exception as e:
            return RunResult(
                success=False,
                error=f"CLI agent '{cmd}' failed to start: {e}",
            )

        stdout_raw = stdout.decode(errors="replace")
        stderr_raw = stderr.decode(errors="replace")
        stdout_text = stdout_raw.strip()
        stderr_text = stderr_raw.strip()

        if proc.returncode != 0:
            return RunResult(
                success=False,
                error=self._format_cli_failure(
                    command=cmd,
                    exit_code=proc.returncode,
                    stdout=stdout_text,
                    stderr=stderr_text,
                ),
                exit_code=proc.returncode,
            )

        return RunResult(
            success=True,
            output=self._combine_cli_output(stdout=stdout_raw, stderr=stderr_raw),
            exit_code=0,
        )

    def _combine_cli_output(self, stdout: str, stderr: str) -> str:
        if stdout and stderr:
            return f"{stdout}\n\n[stderr]\n{stderr}"
        if stdout:
            return stdout
        return stderr

    def _format_cli_failure(
        self,
        command: str,
        exit_code: int,
        stdout: str,
        stderr: str,
    ) -> str:
        details = [
            f"CLI agent '{command}' exited with code {exit_code}.",
            f"Prompt mode: {self.config.prompt_mode}",
        ]
        if stdout:
            details.append(f"stdout: {self._snippet(stdout)}")
        if stderr:
            details.append(f"stderr: {self._snippet(stderr)}")
        if not stdout and not stderr:
            details.append("The agent produced no stdout or stderr output.")
        return " ".join(details)

    def _snippet(self, text: str, limit: int = 800) -> str:
        if len(text) <= limit:
            return text
        return f"{text[:limit]}..."

    async def _run_api(self, prompt: str, system_message: str | None = None) -> RunResult:
        provider = (self.config.provider or "unknown").lower()

        if provider == "anthropic":
            api_key = os.getenv("ANTHROPIC_API_KEY")
            if not api_key:
                return RunResult(
                    success=False,
                    error="Missing ANTHROPIC_API_KEY environment variable.",
                )
            if AsyncAnthropic is None:
                return RunResult(success=False, error="Anthropic SDK is not installed.")

            client = AsyncAnthropic(api_key=api_key)
            try:
                response = await client.messages.create(
                    model=self.config.model,
                    max_tokens=4096,
                    system=system_message,
                    messages=[{"role": "user", "content": prompt}],
                )
            except Exception as e:
                return RunResult(success=False, error=str(e))

            text = response.content[0].text if response.content else ""
            return RunResult(success=True, output=text)

        if provider == "openai":
            api_key = os.getenv("OPENAI_API_KEY")
            if not api_key:
                return RunResult(
                    success=False,
                    error="Missing OPENAI_API_KEY environment variable.",
                )
            if AsyncOpenAI is None:
                return RunResult(success=False, error="OpenAI SDK is not installed.")

            client = AsyncOpenAI(api_key=api_key)
            messages = []
            if system_message:
                messages.append({"role": "system", "content": system_message})
            messages.append({"role": "user", "content": prompt})

            try:
                response = await client.chat.completions.create(
                    model=self.config.model,
                    messages=messages,
                )
            except Exception as e:
                return RunResult(success=False, error=str(e))

            text = response.choices[0].message.content if response.choices else ""
            return RunResult(success=True, output=text)

        return RunResult(
            success=False,
            error=(
                f"API provider '{provider}' is not supported. "
                "Supported providers: anthropic, openai."
            ),
        )
