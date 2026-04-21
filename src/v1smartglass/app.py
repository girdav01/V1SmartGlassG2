"""Orchestrator: voice-triggered Vision One → G2 HUD pipeline."""

from __future__ import annotations

import asyncio
import logging

from .config import Settings
from .formatter import Frame, build_frames
from .glasses import GlassesDriver, build_driver
from .vision_one import VisionOneClient
from .voice import Intent, parse_intent

log = logging.getLogger(__name__)


class App:
    def __init__(self, settings: Settings, *, driver: GlassesDriver | None = None) -> None:
        self._settings = settings
        self._driver = driver or build_driver(settings.glasses, dry_run=settings.app.dry_run)
        self._client = VisionOneClient(settings.vision_one)
        self._lock = asyncio.Lock()

    async def run(self) -> None:
        await self._driver.connect()
        try:
            async with self._client:
                # Show a ready banner, then hand control to the voice loop.
                await self._driver.display(
                    [Frame(title="V1 SMARTGLASS", lines=["Say 'Hey Even VisionOne alerts'", "or 'Hey Even top risk'."])]
                )
                await self._driver.listen_voice(self._on_utterance)
        finally:
            await self._driver.disconnect()

    async def run_once(self, intent: Intent) -> None:
        """Connect, fetch + render a single intent, disconnect. Used by CLI."""
        await self._driver.connect()
        try:
            async with self._client:
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
        return [Frame(title="V1 SMARTGLASS", lines=["Sorry, I didn't catch that."])]

    async def _on_utterance(self, utterance: str) -> None:
        intent = parse_intent(utterance)
        log.info("voice utterance=%r -> intent=%s", utterance, intent.value)
        if intent is Intent.UNKNOWN:
            return
        # Serialise so two concurrent voice commands don't fight over the HUD.
        async with self._lock:
            frames = await self.handle(intent)
            await self._driver.display(frames)
