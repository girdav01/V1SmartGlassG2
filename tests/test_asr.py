from v1smartglass.asr import build_transcriber
from v1smartglass.config import AsrConfig


def test_disabled_returns_none() -> None:
    assert build_transcriber(AsrConfig(enabled=False)) is None


def test_enabled_returns_none_when_extras_missing(monkeypatch) -> None:
    """If the [asr] extra isn't installed, build_transcriber returns None
    rather than blowing up — callers fall back to wake-cycle."""
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name in ("faster_whisper", "sounddevice"):
            raise ImportError(name)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    assert build_transcriber(AsrConfig(enabled=True)) is None
