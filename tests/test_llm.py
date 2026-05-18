import os

import pytest

from v1smartglass.config import GlassesConfig, LlmConfig, McpServerConfig
from v1smartglass.formatter import answer_frame
from v1smartglass.llm import LlmHost, _resolve_env, _shrink


def test_shrink_collapses_whitespace_and_truncates() -> None:
    text = "VisionOne:  alice@corp\nrisk=95\t(suspicious login from RU)" * 5
    out = _shrink(text, max_chars=160)
    assert len(out) <= 160
    assert "  " not in out
    assert out.endswith("…")


def test_resolve_env_substitutes_placeholders(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("V1SG_API_KEY", "secret123")
    monkeypatch.delenv("MISSING_VAR", raising=False)
    resolved = _resolve_env({
        "TREND_VISION_ONE_API_KEY": "${V1SG_API_KEY}",
        "STATIC": "literal-value",
        "BLANK": "${MISSING_VAR}",
    })
    assert resolved["TREND_VISION_ONE_API_KEY"] == "secret123"
    assert resolved["STATIC"] == "literal-value"
    assert resolved["BLANK"] == ""


def test_disabled_servers_are_filtered() -> None:
    host = LlmHost(
        LlmConfig(enabled=True),
        [
            McpServerConfig(name="a", command="echo", enabled=True),
            McpServerConfig(name="b", command="echo", enabled=False),
        ],
    )
    assert [s.name for s in host._servers_cfg] == ["a"]


async def test_ask_without_start_raises() -> None:
    host = LlmHost(LlmConfig(enabled=True), [])
    with pytest.raises(RuntimeError, match="start"):
        await host.ask("anything")


def test_answer_frame_wraps_long_text_to_hud() -> None:
    g = GlassesConfig(line_chars=24, max_lines=5)
    text = "VisionOne reports alice@corp logged in from Moscow at 02:13 UTC, score 95."
    frame = answer_frame(text, g)
    assert all(len(line) <= 24 for line in frame.lines)
    assert len(frame.lines) == 4  # max_lines - 1 body lines


def test_answer_frame_truncates_overflow_with_ellipsis() -> None:
    g = GlassesConfig(line_chars=16, max_lines=3)  # only 2 body lines × 16 chars
    text = "The answer is far longer than the available HUD space and should overflow."
    frame = answer_frame(text, g)
    assert len(frame.lines) == 2
    assert frame.lines[-1].endswith("…")
