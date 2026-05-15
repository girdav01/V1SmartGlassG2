"""Host-microphone ASR for routing 'Hey Even ...' phrases on the G2.

The G2 hardware does the wake-word locally and forwards a START_AI event
over BLE — but no transcript and no Python-decodable audio. So when the
wake event fires we record a short window from the *host* microphone
(sounddevice) and feed the PCM through faster-whisper.

Both dependencies are in the optional `[asr]` extra; if either is missing
we raise at construction time and the glasses driver falls back to its
wake-cycle UX.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Protocol

from .config import AsrConfig

log = logging.getLogger(__name__)


class Transcriber(Protocol):
    async def listen_and_transcribe(self) -> str: ...


class WhisperTranscriber:
    """Record a fixed window from the default mic and transcribe with Whisper."""

    def __init__(self, cfg: AsrConfig) -> None:
        self._cfg = cfg
        self._model = None  # loaded lazily on first call

    def _ensure_deps(self) -> tuple[object, object, object]:
        try:
            import numpy as np
            import sounddevice as sd
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise RuntimeError(
                "ASR dependencies missing. Install with `pip install \"v1smartglass[asr]\"` "
                "or set asr.enabled=false to use the wake-cycle fallback."
            ) from exc
        return np, sd, WhisperModel

    def _load_model(self):
        if self._model is None:
            _, _, WhisperModel = self._ensure_deps()
            log.info("loading whisper model=%s device=%s compute_type=%s",
                     self._cfg.model, self._cfg.device, self._cfg.compute_type)
            self._model = WhisperModel(
                self._cfg.model,
                device=self._cfg.device,
                compute_type=self._cfg.compute_type,
            )
        return self._model

    async def listen_and_transcribe(self) -> str:
        np, sd, _ = self._ensure_deps()
        loop = asyncio.get_running_loop()

        def _record_and_decode() -> str:
            frames = int(self._cfg.record_seconds * self._cfg.sample_rate)
            log.info("recording %.1fs from mic device=%s", self._cfg.record_seconds, self._cfg.mic_device)
            audio = sd.rec(
                frames,
                samplerate=self._cfg.sample_rate,
                channels=1,
                dtype="float32",
                device=self._cfg.mic_device,
            )
            sd.wait()
            model = self._load_model()
            segments, _info = model.transcribe(
                audio.flatten(),
                language=self._cfg.language,
                beam_size=1,
                vad_filter=True,
            )
            return " ".join(seg.text.strip() for seg in segments).strip()

        return await loop.run_in_executor(None, _record_and_decode)


def build_transcriber(cfg: AsrConfig) -> Transcriber | None:
    """Return a Transcriber if ASR is enabled and importable, else None.

    Returning None lets callers fall back to a non-ASR voice flow without
    surfacing the ImportError until someone actually tries to transcribe.
    """
    if not cfg.enabled:
        return None
    try:
        import faster_whisper  # noqa: F401
        import sounddevice  # noqa: F401
    except ImportError:
        log.warning("asr.enabled=true but the [asr] extra is not installed; falling back to wake-cycle")
        return None
    return WhisperTranscriber(cfg)
