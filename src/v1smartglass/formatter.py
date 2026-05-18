"""Turn Vision One data into compact HUD frames for the G2 display.

The G2 HUD has limited real estate (~5 lines of ~32 chars at the default
font). We emit a list of "pages" that the glasses driver cycles through.
"""

from __future__ import annotations

from dataclasses import dataclass

from .config import GlassesConfig
from .vision_one import Alert, RiskEntity

SEVERITY_GLYPH = {"critical": "!!", "high": "! ", "medium": "~ ", "low": ". "}


@dataclass(slots=True)
class Frame:
    title: str
    lines: list[str]

    def render(self) -> str:
        return "\n".join([self.title, *self.lines])


def build_frames(
    alerts: list[Alert],
    risky_users: list[RiskEntity],
    risky_devices: list[RiskEntity],
    glasses: GlassesConfig,
    top_n: int,
) -> list[Frame]:
    return [
        _alert_frame(alerts, glasses),
        _risk_frame("TOP RISKY USERS", risky_users, glasses, top_n),
        _risk_frame("TOP RISKY DEVICES", risky_devices, glasses, top_n),
    ]


def _alert_frame(alerts: list[Alert], glasses: GlassesConfig) -> Frame:
    title = _truncate(f"V1 ALERTS ({len(alerts)})", glasses.line_chars)
    if not alerts:
        return Frame(title=title, lines=["No alerts in window."])

    # Sort: critical > high > medium > low, then newest first.
    order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    ranked = sorted(alerts, key=lambda a: (order.get(a.severity, 9), -a.created_at.timestamp()))

    lines: list[str] = []
    for alert in ranked[: glasses.max_lines - 1]:
        glyph = SEVERITY_GLYPH.get(alert.severity, "  ")
        who = alert.impacted_entities[0] if alert.impacted_entities else "-"
        line = f"{glyph}{alert.model} [{who}]"
        lines.append(_truncate(line, glasses.line_chars))
    return Frame(title=title, lines=lines)


def _risk_frame(title: str, entities: list[RiskEntity], glasses: GlassesConfig, top_n: int) -> Frame:
    title = _truncate(title, glasses.line_chars)
    if not entities:
        return Frame(title=title, lines=["No risk data."])

    lines: list[str] = []
    for idx, entity in enumerate(entities[:top_n], start=1):
        line = f"{idx}. {entity.name}  ({entity.score})"
        lines.append(_truncate(line, glasses.line_chars))
    while len(lines) < min(top_n, glasses.max_lines - 1):
        lines.append("")
    return Frame(title=title, lines=lines)


def _truncate(text: str, width: int) -> str:
    return text if len(text) <= width else text[: width - 1] + "…"


def answer_frame(text: str, glasses: GlassesConfig, *, title: str = "ASK") -> Frame:
    """Word-wrap free-form text into the HUD budget.

    Used for LLM answers: collapses whitespace, soft-wraps on spaces, then
    hard-truncates the final line with an ellipsis if the response still
    overflows the available lines.
    """
    body_lines = glasses.max_lines - 1
    flat = " ".join(text.split())
    if not flat:
        return Frame(title=title, lines=[""] * body_lines)

    lines: list[str] = []
    remaining = flat
    while remaining and len(lines) < body_lines:
        if len(remaining) <= glasses.line_chars:
            lines.append(remaining)
            remaining = ""
            break
        # soft-wrap on the last space within line_chars
        cut = remaining.rfind(" ", 0, glasses.line_chars + 1)
        if cut <= 0:
            cut = glasses.line_chars
        lines.append(remaining[:cut].rstrip())
        remaining = remaining[cut:].lstrip()

    if remaining and lines:
        # text outstripped the line budget — tail-ellipsise the last line
        tail = lines[-1]
        budget = glasses.line_chars - 1
        lines[-1] = (tail[:budget].rstrip() + "…") if len(tail) >= budget else tail + "…"

    while len(lines) < body_lines:
        lines.append("")
    return Frame(title=_truncate(title, glasses.line_chars), lines=lines)
