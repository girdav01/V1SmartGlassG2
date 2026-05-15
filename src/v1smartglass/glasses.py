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
    """Real driver backed by the community `even-glasses` package (>=0.1.11).

    Voice flow:
      The G2 fires a START_AI notification each time the 'Hey Even' wake word
      is detected on the temple, then streams LC3-encoded mic audio. The
      `even-glasses` package surfaces the wake event and the raw audio but
      does NOT include ASR — turning audio into text is the host's job.

      Since we don't bundle an ASR here, this driver implements a
      'wake-cycle' UX: each wake event rotates between intents (ALERTS →
      TOP_RISK → ALERTS …) and feeds a synthetic utterance to the callback.
      To get real per-phrase routing, replace the wake hook with one that
      streams mic data into your ASR of choice (e.g. faster-whisper) and
      feeds the transcript through `on_utterance`.
    """

    _CYCLE = ("Hey Even VisionOne alerts", "Hey Even Vision One top risk")

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

        self._glasses = GlassesManager(
            left_name=self._cfg.left_name,
            right_name=self._cfg.right_name,
        )
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
        # Monkey-patch the start-AI handler so each wake event enqueues a
        # synthetic utterance. The package's default handler still runs first.
        from even_glasses import notification_handlers as nh

        queue: asyncio.Queue[str] = asyncio.Queue()
        original = nh.handle_start_ai

        async def patched(glass, sender, data) -> None:  # type: ignore[no-untyped-def]
            await original(glass, sender, data)
            await queue.put(self._next_utterance())

        nh.handle_start_ai = patched  # type: ignore[assignment]
        try:
            while True:
                utterance = await queue.get()
                await on_utterance(utterance)
        finally:
            nh.handle_start_ai = original  # type: ignore[assignment]

    def _next_utterance(self) -> str:
        idx = getattr(self, "_cycle_idx", 0)
        self._cycle_idx = (idx + 1) % len(self._CYCLE)
        return self._CYCLE[idx]

    async def disconnect(self) -> None:
        if self._glasses is not None:
            await self._glasses.disconnect_all()
            self._glasses = None


def build_driver(cfg: GlassesConfig, *, dry_run: bool) -> GlassesDriver:
    if dry_run:
        return ConsoleDriver()
    try:
        import even_glasses  # noqa: F401
    except ImportError:
        return ConsoleDriver()
    return EvenG2Driver(cfg)
