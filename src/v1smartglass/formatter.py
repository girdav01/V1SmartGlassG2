"""Turn Vision One data into compact HUD frames for the G2 display.

The G2 HUD has limited real estate (~5 lines of ~32 chars at the default
font). We emit a list of "pages" that the glasses driver cycles through.
"""

from __future__ import annotations

from dataclasses import dataclass

from .config import GlassesConfig
from .news import Article
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


def _wrap(text: str, width: int, max_lines: int) -> list[str]:
    """Soft-wrap on spaces; if the result overflows, ellipsise the last line."""
    flat = " ".join((text or "").split())
    if not flat:
        return []
    lines: list[str] = []
    remaining = flat
    while remaining and len(lines) < max_lines:
        if len(remaining) <= width:
            lines.append(remaining)
            remaining = ""
            break
        cut = remaining.rfind(" ", 0, width + 1)
        if cut <= 0:
            cut = width
        lines.append(remaining[:cut].rstrip())
        remaining = remaining[cut:].lstrip()
    if remaining and lines:
        tail = lines[-1]
        budget = width - 1
        lines[-1] = (tail[:budget].rstrip() + "…") if len(tail) >= budget else tail + "…"
    return lines


def answer_frame(text: str, glasses: GlassesConfig, *, title: str = "ASK") -> Frame:
    """Word-wrap free-form text into the HUD budget.

    Used for LLM answers: collapses whitespace, soft-wraps on spaces, then
    hard-truncates the final line with an ellipsis if the response still
    overflows the available lines.
    """
    body_lines = glasses.max_lines - 1
    lines = _wrap(text, glasses.line_chars, body_lines)
    while len(lines) < body_lines:
        lines.append("")
    return Frame(title=_truncate(title, glasses.line_chars), lines=lines)


def news_frames(
    articles: list[Article],
    source_label: str,
    glasses: GlassesConfig,
) -> list[Frame]:
    """Build the mixed digest + per-article frame set for the HUD.

    Frame 1: digest of the top-3 headlines (title only, one per line).
    Frames 2..N: one card per article with wrapped title + AI summary,
    paginated by the SDK.
    """
    body_lines = glasses.max_lines - 1
    title = _truncate(source_label.upper(), glasses.line_chars)

    if not articles:
        return [Frame(title=title, lines=["No items.", "Check feed config."] + [""] * max(0, body_lines - 2))]

    # --- digest frame (top 3) ---
    digest_lines: list[str] = []
    for idx, article in enumerate(articles[:3], start=1):
        digest_lines.append(_truncate(f"{idx}. {article.title}", glasses.line_chars))
    while len(digest_lines) < body_lines:
        digest_lines.append("")
    digest = Frame(title=title, lines=digest_lines[:body_lines])

    # --- per-article detail cards ---
    detail_frames: list[Frame] = []
    total = len(articles)
    for idx, article in enumerate(articles, start=1):
        card_title = _truncate(f"{source_label.upper()} {idx}/{total}", glasses.line_chars)
        # Split body budget between title and summary. We want at least 1 line
        # of summary, so cap the title at body_lines - 1.
        title_lines = _wrap(article.title, glasses.line_chars, max_lines=body_lines - 1)
        summary_budget = max(1, body_lines - len(title_lines))
        summary_lines = _wrap(article.summary, glasses.line_chars, max_lines=summary_budget)
        card_lines = title_lines + summary_lines
        while len(card_lines) < body_lines:
            card_lines.append("")
        detail_frames.append(Frame(title=card_title, lines=card_lines[:body_lines]))

    return [digest, *detail_frames]
