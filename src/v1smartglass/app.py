"""Orchestrator: voice-triggered Vision One → G2 HUD pipeline."""

from __future__ import annotations

import asyncio
import logging

from .asr import build_transcriber
from .config import Settings
from .formatter import Frame, answer_frame, build_frames
from .glasses import GlassesDriver, build_driver
from .llm import LlmHost
from .vision_one import VisionOneClient
from .voice import Intent, extract_ask_query, parse_intent

log = logging.getLogger(__name__)


class App:
    def __init__(self, settings: Settings, *, driver: GlassesDriver | None = None) -> None:
        self._settings = settings
        self._driver = driver or build_driver(
            settings.glasses,
            dry_run=settings.app.dry_run,
            transcriber=build_transcriber(settings.asr),
        )
        self._client = VisionOneClient(settings.vision_one)
        self._llm: LlmHost | None = (
            LlmHost(settings.llm, settings.mcp_servers) if settings.llm.enabled else None
        )
        self._lock = asyncio.Lock()
        # Holds the last utterance so handle(Intent.ASK) knows what to ask.
        self._pending_query: str = ""

    async def run(self) -> None:
        await self._driver.connect()
        try:
            async with self._client:
                async with _maybe(self._llm):
                    await self._driver.display(
                        [
                            Frame(
                                title="V1 SMARTGLASS",
                                lines=[
                                    "Say 'Hey Even VisionOne alerts',",
                                    "'Hey Even top risk',",
                                    "or 'Hey Even ask <question>'.",
                                ],
                            )
                        ]
                    )
                    await self._driver.listen_voice(self._on_utterance)
        finally:
            await self._driver.disconnect()

    async def run_once(self, intent: Intent, *, query: str = "") -> None:
        """Connect, fetch + render a single intent, disconnect. Used by CLI."""
        self._pending_query = query
        await self._driver.connect()
        try:
            async with self._client:
                async with _maybe(self._llm):
                    frames = await self.handle(intent)
                    await self._driver.display(frames)
        finally:
            await self._driver.disconnect()

    async def handle(self, intent: Intent) -> list[Frame]:
        """Public entry point — useful for tests and the `once` CLI command."""
        if intent is Intent.ALERTS:
            alerts = await self._client.fetch_alerts()
            return [build_frames(alerts, [], [], self._settings.glasses, self._settings.app.top_n)[0]]
        if intent is Intent.TOP_RISK:
            users, devices = await asyncio.gather(
                self._client.fetch_top_risky_users(self._settings.app.top_n),
                self._client.fetch_top_risky_devices(self._settings.app.top_n),
            )
            frames = build_frames([], users, devices, self._settings.glasses, self._settings.app.top_n)
            return frames[1:]  # skip the alerts frame
        if intent is Intent.ASK:
            return await self._handle_ask(self._pending_query)
        return [Frame(title="V1 SMARTGLASS", lines=["Sorry, I didn't catch that."])]

    async def _handle_ask(self, query: str) -> list[Frame]:
        if self._llm is None:
            return [Frame(title="V1 SMARTGLASS", lines=["LLM disabled.", "Enable llm: in config."])]
        if not query:
            return [Frame(title="V1 SMARTGLASS", lines=["Ask what? Try:", "'Hey Even, why is X risky'."])]
        # Show a holding frame so the wearer knows the request landed.
        await self._driver.display([Frame(title="ASK", lines=[_truncate(query, self._settings.glasses.line_chars), "thinking…"])])
        answer = await self._llm.ask(query)
        return [answer_frame(answer or "(no answer)", self._settings.glasses)]

    async def _on_utterance(self, utterance: str) -> None:
        intent = parse_intent(utterance)
        log.info("voice utterance=%r -> intent=%s", utterance, intent.value)
        if intent is Intent.UNKNOWN:
            return
        async with self._lock:
            self._pending_query = extract_ask_query(utterance) if intent is Intent.ASK else ""
            frames = await self.handle(intent)
            await self._driver.display(frames)


class _maybe:
    """Async context manager that no-ops if its inner object is None.

    Lets us write `async with _maybe(self._llm):` instead of branching on
    whether the LLM is configured.
    """

    def __init__(self, inner: object | None) -> None:
        self._inner = inner

    async def __aenter__(self) -> object | None:
        if self._inner is None:
            return None
        return await self._inner.__aenter__()  # type: ignore[attr-defined]

    async def __aexit__(self, *exc: object) -> None:
        if self._inner is None:
            return None
        return await self._inner.__aexit__(*exc)  # type: ignore[attr-defined]


def _truncate(text: str, width: int) -> str:
    return text if len(text) <= width else text[: width - 1] + "…"
