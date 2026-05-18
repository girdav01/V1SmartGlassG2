"""LLM host: wires an OpenAI-compatible model to a fleet of MCP servers.

Uses the `openai-agents` SDK (https://pypi.org/project/openai-agents/) for the
function-calling loop and `MCPServerStdio` / `MCPServerStreamableHttp` for
the MCP transports. The model can point at any OpenAI-compatible endpoint
— OpenAI itself, a local Ollama/LMStudio, or an LLM proxy like LiteLLM.

Voice → Intent.ASK → LlmHost.ask(query) → string answer for the HUD.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from contextlib import AsyncExitStack
from string import Template
from typing import Any

from .config import LlmConfig, McpServerConfig

log = logging.getLogger(__name__)

_DEFAULT_SYSTEM_PROMPT = """\
You are a security operations assistant displayed on smart glasses.

CONSTRAINTS:
- Your answer renders on a 5-line, 32-character monochrome HUD.
- Keep replies under 160 characters total. No markdown, no bullets, no emoji.
- Prefer concrete facts over hedging. State the answer; don't restate the
  question.
- When data is from a tool, name the source briefly (e.g. "VisionOne:",
  "Shodan:", "MISP:").

TOOL USE:
- You have MCP tools for: Trend Vision One (workbench alerts, ASRM risky
  users/devices, threat intel), Splunk, MISP, Shodan, AbuseIPDB.
- Pick the smallest set of tool calls needed to answer. Prefer Vision One
  for SOC questions about alerts, users, devices, and risk.
- If you can't get the answer in {max_turns} tool calls, summarise what
  you do know and stop.
"""


class LlmHost:
    """Manages MCP server lifetimes and answers ASK queries via an LLM."""

    def __init__(self, llm_cfg: LlmConfig, mcp_servers: list[McpServerConfig]) -> None:
        self._llm = llm_cfg
        self._servers_cfg = [s for s in mcp_servers if s.enabled]
        self._stack: AsyncExitStack | None = None
        self._agent: Any = None  # agents.Agent — typed loosely so tests can mock
        self._oai_client: Any = None  # raw AsyncOpenAI for cheap one-shot calls
        self._lock = asyncio.Lock()

    async def __aenter__(self) -> "LlmHost":
        await self.start()
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.stop()

    async def start(self) -> None:
        if self._agent is not None:
            return
        try:
            from agents import (
                Agent,
                AsyncOpenAI,
                set_default_openai_api,
                set_default_openai_client,
            )
            from agents.mcp import MCPServerStdio, MCPServerStreamableHttp
        except ImportError as exc:
            raise RuntimeError(
                "LLM dependencies missing. Install with `pip install \"v1smartglass[llm]\"` "
                "or set llm.enabled=false."
            ) from exc

        client = AsyncOpenAI(api_key=self._llm.api_key, base_url=self._llm.base_url)
        self._oai_client = client
        set_default_openai_client(client, use_for_tracing=False)
        # Chat Completions is the lowest-common-denominator API — works with
        # OpenAI, Ollama, LMStudio, vLLM, and most LiteLLM proxies. The
        # Responses API (the agents SDK default) is OpenAI-only today.
        set_default_openai_api("chat_completions")

        self._stack = AsyncExitStack()
        servers: list[Any] = []
        for cfg in self._servers_cfg:
            if cfg.transport == "stdio":
                if not cfg.command:
                    raise ValueError(f"MCP server {cfg.name!r} has stdio transport but no command")
                params = {
                    "command": cfg.command,
                    "args": list(cfg.args),
                    "env": _resolve_env(cfg.env),
                }
                server = MCPServerStdio(
                    params=params,
                    name=cfg.name,
                    cache_tools_list=True,
                    tool_filter=_tool_filter(cfg.tools),
                )
            elif cfg.transport == "http":
                if not cfg.url:
                    raise ValueError(f"MCP server {cfg.name!r} has http transport but no url")
                server = MCPServerStreamableHttp(
                    params={"url": cfg.url},
                    name=cfg.name,
                    cache_tools_list=True,
                    tool_filter=_tool_filter(cfg.tools),
                )
            else:  # pragma: no cover - validated by pydantic
                raise ValueError(f"Unknown MCP transport {cfg.transport!r}")

            await self._stack.enter_async_context(server)
            servers.append(server)
            log.info("mcp server up: %s", cfg.name)

        instructions = (
            self._llm.system_prompt
            if self._llm.system_prompt
            else Template(_DEFAULT_SYSTEM_PROMPT).safe_substitute(max_turns=self._llm.max_turns)
        )
        self._agent = Agent(
            name="v1smartglass",
            instructions=instructions,
            model=self._llm.model,
            mcp_servers=servers,
        )

    async def stop(self) -> None:
        if self._stack is not None:
            await self._stack.aclose()
            self._stack = None
        self._agent = None
        self._oai_client = None

    async def summarise(self, title: str, snippet: str, *, max_chars: int = 96) -> str:
        """Cheap one-shot summary for a news headline.

        Bypasses the Agent / MCP loop entirely — this is a single chat
        completion against the OpenAI-compatible endpoint. Used by the news
        feed pipeline where we want lots of tiny summaries fast, not the
        full tool-using agent.
        """
        if self._oai_client is None:
            raise RuntimeError("LlmHost.start() must be called before summarise().")
        system = (
            "You summarise cybersecurity news for a heads-up display. "
            f"Reply with ONE plain-text line, under {max_chars} characters, "
            "concrete and technical. No markdown, no quotes, no preamble."
        )
        user = f"Headline: {title}\n\nSnippet: {snippet}".strip()
        resp = await asyncio.wait_for(
            self._oai_client.chat.completions.create(
                model=self._llm.model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                temperature=0.2,
                max_tokens=80,
            ),
            timeout=self._llm.timeout_seconds,
        )
        text = (resp.choices[0].message.content or "").strip()
        return _shrink(text, max_chars)

    async def ask(self, query: str) -> str:
        """Run one ASK round-trip and return the trimmed answer for the HUD."""
        if self._agent is None:
            raise RuntimeError("LlmHost.start() must be called before ask().")
        if not query.strip():
            return ""

        from agents import Runner

        async with self._lock:  # serialise concurrent ASKs
            try:
                result = await asyncio.wait_for(
                    Runner.run(self._agent, input=query, max_turns=self._llm.max_turns),
                    timeout=self._llm.timeout_seconds,
                )
            except asyncio.TimeoutError:
                log.warning("LLM ask timed out after %.1fs", self._llm.timeout_seconds)
                return "LLM timeout."
            except Exception as exc:  # noqa: BLE001
                log.exception("LLM ask failed")
                return f"LLM error: {type(exc).__name__}"

        text = (result.final_output or "").strip()
        return _shrink(text, self._llm.max_chars)


def _resolve_env(env: dict[str, str]) -> dict[str, str]:
    """Substitute ${VAR} placeholders from the process environment.

    Lets config.yaml reference secrets stored as env vars (e.g.
    `TREND_VISION_ONE_API_KEY: "${V1SG_API_KEY}"`) without copy-pasting.
    Missing vars resolve to an empty string and emit a warning.
    """
    resolved: dict[str, str] = {}
    for key, raw in env.items():
        match = re.fullmatch(r"\$\{([A-Z0-9_]+)\}", raw)
        if match:
            value = os.environ.get(match.group(1), "")
            if not value:
                log.warning("env var %s referenced by MCP config is unset", match.group(1))
            resolved[key] = value
        else:
            resolved[key] = raw
    return resolved


def _tool_filter(allowlist: list[str]):
    """Return an `openai-agents` tool filter, or None to pass everything."""
    if not allowlist:
        return None
    from agents.mcp import create_static_tool_filter

    return create_static_tool_filter(allowed_tool_names=allowlist)


def _shrink(text: str, max_chars: int) -> str:
    """Collapse whitespace and hard-truncate to fit the HUD."""
    flat = re.sub(r"\s+", " ", text).strip()
    if len(flat) <= max_chars:
        return flat
    return flat[: max_chars - 1].rstrip() + "…"
