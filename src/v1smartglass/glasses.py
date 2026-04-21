"""Driver for the Even Realities G2 HUD.

Uses the community Python SDK `even-glasses` (the de-facto G2 BLE SDK),
which implements the reverse-engineered BLE protocol: scan both temples
(left/right arm), pair, and push text pages using the TEXT command frames.

Install with:  pip install "v1smartglass[even]"

If the extra isn't installed, or `dry_run=true` in config, the driver
prints frames to stdout instead of sending them to a device. That makes
the app runnable on CI and on machines without a BLE adapter.
"""

from __future__ import annotations

import asyncio
from typing import Awaitable, Callable, Protocol

from rich.console import Console
from rich.panel import Panel

from .config import GlassesConfig
from .formatter import Frame

VoiceCallback = Callable[[str], Awaitable[None]]


class GlassesDriver(Protocol):
    async def connect(self) -> None: ...
    async def display(self, frames: list[Frame]) -> None: ...
    async def listen_voice(self, on_utterance: VoiceCallback) -> None: ...
    async def disconnect(self) -> None: ...


class ConsoleDriver:
    """Prints frames as panels — used when dry_run=true or even-glasses is absent.

    Reads fake voice commands from stdin so you can exercise the intent
    router without a BLE adapter:  type `Hey Even VisionOne alerts` + Enter.
    """

    def __init__(self) -> None:
        self._console = Console()

    async def connect(self) -> None:
        self._console.log("[dim]console driver ready (dry run)[/dim]")
        self._console.log("[dim]Type 'Hey Even ...' utterances and press Enter to simulate voice.[/dim]")

    async def display(self, frames: list[Frame]) -> None:
        for frame in frames:
            body = "\n".join(frame.lines)
            self._console.print(Panel(body, title=frame.title, border_style="cyan"))

    async def listen_voice(self, on_utterance: VoiceCallback) -> None:
        loop = asyncio.get_running_loop()
        while True:
            line = await loop.run_in_executor(None, _read_line)
            if line is None:
                return
            await on_utterance(line)

    async def disconnect(self) -> None:
        return None


def _read_line() -> str | None:
    try:
        return input()
    except EOFError:
        return None


class EvenG2Driver:
    """Real driver backed by the community `even-glasses` package."""

    def __init__(self, cfg: GlassesConfig) -> None:
        self._cfg = cfg
        self._glasses = None  # lazy-imported

    async def connect(self) -> None:
        try:
            from even_glasses.bluetooth_manager import GlassesManager
        except ImportError as exc:  # pragma: no cover - optional dep
            raise RuntimeError(
                "even-glasses is not installed. Run `pip install \"v1smartglass[even]\"` "
                "or set app.dry_run=true."
            ) from exc

        self._glasses = GlassesManager(device_name=self._cfg.device_name)
        ok = await self._glasses.scan_and_connect()
        if not ok:
            raise RuntimeError("Could not pair with Even Realities G2. Make sure both arms are on.")

    async def display(self, frames: list[Frame]) -> None:
        if self._glasses is None:
            raise RuntimeError("connect() must be called before display().")
        from even_glasses.commands import send_text  # pragma: no cover - optional dep

        for frame in frames:
            text = "\n".join([frame.title, *frame.lines])
            await send_text(self._glasses, text)
            await asyncio.sleep(3.0)  # let the wearer read it

    async def listen_voice(self, on_utterance: VoiceCallback) -> None:  # pragma: no cover - BLE
        if self._glasses is None:
            raise RuntimeError("connect() must be called before listen_voice().")
        # even-glasses exposes voice transcripts through an async iterator on the
        # manager. Each item is the utterance captured after the 'Hey Even' wake
        # word is detected by the on-arm DSP.
        async for utterance in self._glasses.voice_commands():
            await on_utterance(str(utterance))

    async def disconnect(self) -> None:
        if self._glasses is not None:
            await self._glasses.disconnect()
            self._glasses = None


def build_driver(cfg: GlassesConfig, *, dry_run: bool) -> GlassesDriver:
    if dry_run:
        return ConsoleDriver()
    try:
        import even_glasses  # noqa: F401
    except ImportError:
        return ConsoleDriver()
    return EvenG2Driver(cfg)
