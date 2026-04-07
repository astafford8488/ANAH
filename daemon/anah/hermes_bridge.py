"""Hermes Agent bridge — delegates tasks to a Hermes Agent instance.

Supports two modes:
1. API mode: Hermes running as an OpenAI-compatible HTTP endpoint (default)
2. RPC mode: Hermes spawned as a subprocess with JSON Lines over stdin/stdout

Hermes Agent (by Nous Research) is a self-improving autonomous agent with
persistent memory, skill creation, and 40+ built-in tools.
"""

import asyncio
import json
import logging
import os
from dataclasses import dataclass, field
from typing import AsyncIterator

logger = logging.getLogger("anah.hermes")


@dataclass
class HermesConfig:
    """Configuration for connecting to a Hermes Agent instance."""
    enabled: bool = False
    mode: str = "api"  # "api" or "rpc"
    # API mode settings
    api_url: str = "http://localhost:11434/v1"  # Hermes API server endpoint
    api_key: str = ""  # Optional API key
    model: str = "hermes"  # Model name for the API
    # RPC mode settings
    hermes_path: str = "hermes"  # Path to hermes binary
    # Shared settings
    timeout: int = 120  # Max seconds per task
    task_types: list[str] = field(default_factory=lambda: ["hermes"])  # Which task types route to Hermes


@dataclass
class HermesResult:
    """Result from a Hermes Agent task execution."""
    success: bool
    output: str
    duration_ms: float = 0
    tool_calls: list[dict] = field(default_factory=list)
    error: str | None = None


class HermesBridge:
    """Bridge between ANAH task executor and Hermes Agent."""

    def __init__(self, config: HermesConfig):
        self.config = config
        self._process: asyncio.subprocess.Process | None = None

    @property
    def is_available(self) -> bool:
        return self.config.enabled

    async def execute_task(self, task: dict) -> HermesResult:
        """Execute a task via Hermes Agent. Routes to API or RPC mode."""
        if self.config.mode == "api":
            return await self._execute_api(task)
        elif self.config.mode == "rpc":
            return await self._execute_rpc(task)
        else:
            return HermesResult(
                success=False, output="",
                error=f"Unknown Hermes mode: {self.config.mode}",
            )

    async def _execute_api(self, task: dict) -> HermesResult:
        """Execute a task via Hermes OpenAI-compatible API endpoint."""
        import httpx

        title = task.get("title", "")
        description = task.get("description", "")
        prompt = self._build_prompt(title, description)

        headers = {"content-type": "application/json"}
        if self.config.api_key:
            headers["authorization"] = f"Bearer {self.config.api_key}"

        try:
            async with httpx.AsyncClient(timeout=self.config.timeout) as client:
                resp = await client.post(
                    f"{self.config.api_url}/chat/completions",
                    headers=headers,
                    json={
                        "model": self.config.model,
                        "messages": [
                            {
                                "role": "system",
                                "content": (
                                    "You are an autonomous task executor for the ANAH hierarchy system. "
                                    "Execute the given task and report results. Be concise and actionable. "
                                    "Use your tools as needed to accomplish the task."
                                ),
                            },
                            {"role": "user", "content": prompt},
                        ],
                        "max_tokens": 2048,
                    },
                )

            if resp.status_code != 200:
                return HermesResult(
                    success=False, output="",
                    error=f"Hermes API returned {resp.status_code}: {resp.text[:300]}",
                )

            data = resp.json()
            content = data["choices"][0]["message"]["content"]
            return HermesResult(success=True, output=content)

        except httpx.TimeoutException:
            return HermesResult(
                success=False, output="",
                error=f"Hermes API timed out after {self.config.timeout}s",
            )
        except Exception as e:
            return HermesResult(
                success=False, output="",
                error=f"Hermes API error: {type(e).__name__}: {e}",
            )

    async def _execute_rpc(self, task: dict) -> HermesResult:
        """Execute a task via Hermes RPC subprocess (JSON Lines over stdin/stdout)."""
        title = task.get("title", "")
        description = task.get("description", "")
        prompt = self._build_prompt(title, description)

        try:
            proc = await asyncio.create_subprocess_exec(
                self.config.hermes_path, "--rpc",
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            # Send prompt command
            command = json.dumps({"type": "prompt", "text": prompt}) + "\n"
            proc.stdin.write(command.encode())
            await proc.stdin.drain()

            # Collect output events
            output_parts = []
            tool_calls = []

            try:
                while True:
                    line = await asyncio.wait_for(
                        proc.stdout.readline(),
                        timeout=self.config.timeout,
                    )
                    if not line:
                        break

                    event = json.loads(line.decode().strip())
                    event_type = event.get("type", "")

                    if event_type == "message_delta":
                        output_parts.append(event.get("content", ""))
                    elif event_type == "tool_call":
                        tool_calls.append({
                            "name": event.get("name", ""),
                            "args": event.get("args", {}),
                        })
                    elif event_type == "message_end":
                        break
                    elif event_type == "error":
                        return HermesResult(
                            success=False, output="".join(output_parts),
                            error=event.get("message", "Unknown RPC error"),
                            tool_calls=tool_calls,
                        )

            except asyncio.TimeoutError:
                proc.kill()
                return HermesResult(
                    success=False, output="".join(output_parts),
                    error=f"Hermes RPC timed out after {self.config.timeout}s",
                    tool_calls=tool_calls,
                )

            # Send abort and close
            try:
                abort_cmd = json.dumps({"type": "abort"}) + "\n"
                proc.stdin.write(abort_cmd.encode())
                await proc.stdin.drain()
                proc.stdin.close()
            except Exception:
                pass

            await proc.wait()

            return HermesResult(
                success=True,
                output="".join(output_parts),
                tool_calls=tool_calls,
            )

        except FileNotFoundError:
            return HermesResult(
                success=False, output="",
                error=f"Hermes binary not found at '{self.config.hermes_path}'. Install: curl -fsSL https://raw.githubusercontent.com/NousResearch/hermes-agent/main/scripts/install.sh | bash",
            )
        except Exception as e:
            return HermesResult(
                success=False, output="",
                error=f"Hermes RPC error: {type(e).__name__}: {e}",
            )

    async def health_check(self) -> dict:
        """Check if Hermes Agent is reachable."""
        if not self.config.enabled:
            return {"available": False, "reason": "Hermes integration disabled"}

        if self.config.mode == "api":
            return await self._health_check_api()
        elif self.config.mode == "rpc":
            return await self._health_check_rpc()
        return {"available": False, "reason": f"Unknown mode: {self.config.mode}"}

    async def _health_check_api(self) -> dict:
        """Check if Hermes API server is reachable."""
        import httpx
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.get(f"{self.config.api_url}/models")
            if resp.status_code == 200:
                return {"available": True, "mode": "api", "url": self.config.api_url}
            return {"available": False, "reason": f"API returned {resp.status_code}"}
        except Exception as e:
            return {"available": False, "reason": str(e)}

    async def _health_check_rpc(self) -> dict:
        """Check if Hermes binary exists."""
        import shutil
        found = shutil.which(self.config.hermes_path)
        if found:
            return {"available": True, "mode": "rpc", "path": found}
        return {"available": False, "reason": f"Binary not found: {self.config.hermes_path}"}

    def _build_prompt(self, title: str, description: str) -> str:
        """Build a task execution prompt for Hermes."""
        # Strip the handler prefix from title for cleaner prompting
        clean_title = title
        for prefix in ("hermes:", "hermes_task:", "agent:"):
            if clean_title.lower().startswith(prefix):
                clean_title = clean_title[len(prefix):].strip()
                break

        parts = [f"Task: {clean_title}"]
        if description:
            parts.append(f"Details: {description}")
        parts.append(
            "Execute this task completely. Report what you did and the outcome. "
            "If you cannot complete the task, explain why."
        )
        return "\n\n".join(parts)
