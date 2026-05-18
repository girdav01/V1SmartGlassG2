"""Voice-intent routing for the Even Realities G2 'Hey Even' wake phrase.

The G2 forwards a transcribed utterance to the companion over BLE once the
'Hey Even' wake-word fires. We normalise that transcript and map it to one
of our app intents. Keep the matchers fuzzy: the onboard ASR sometimes
splits 'VisionOne' into 'vision one' or 'virgin one'.
"""

from __future__ import annotations

import enum
import re


class Intent(enum.Enum):
    ALERTS = "alerts"
    TOP_RISK = "top_risk"
    ASK = "ask"
    UNKNOWN = "unknown"


# Each intent has a list of regex patterns. We strip the wake phrase first,
# then try each pattern in order — fast-path intents (ALERTS, TOP_RISK) take
# precedence over ASK so the common cases skip the LLM round-trip.
_WAKE_PHRASE = re.compile(r"^\s*(hey|hi|ok)\s+even[,\s]+", re.IGNORECASE)

_ASK_PREFIX = re.compile(
    r"^\s*(ask|tell\s+me|explain|describe|"
    r"what|why|how|when|where|who|which|is|are|can|does|do)\b[\s,:]*",
    re.IGNORECASE,
)

_PATTERNS: dict[Intent, list[re.Pattern[str]]] = {
    Intent.ALERTS: [
        re.compile(r"\bvision[\s-]?one\b.*\balerts?\b", re.IGNORECASE),
        re.compile(r"\bv1\b.*\balerts?\b", re.IGNORECASE),
        re.compile(r"\balerts?\b.*\bvision[\s-]?one\b", re.IGNORECASE),
    ],
    Intent.TOP_RISK: [
        re.compile(r"\bvision[\s-]?one\b.*\btop\s+risk", re.IGNORECASE),
        re.compile(r"\btop\s+risk(y)?\b", re.IGNORECASE),
        re.compile(r"\brisky\s+(users?|devices?|machines?)\b", re.IGNORECASE),
    ],
}


def parse_intent(utterance: str) -> Intent:
    """Map a transcribed voice command to an Intent.

    Accepts the raw transcript from the glasses, including the wake phrase.
    """
    if not utterance:
        return Intent.UNKNOWN
    stripped = _WAKE_PHRASE.sub("", utterance).strip()
    if not stripped:
        return Intent.UNKNOWN
    for intent, patterns in _PATTERNS.items():
        if any(p.search(stripped) for p in patterns):
            return intent
    if _ASK_PREFIX.match(stripped):
        return Intent.ASK
    return Intent.UNKNOWN


def extract_ask_query(utterance: str) -> str:
    """Return the question portion of an ASK utterance.

    Strips the wake phrase and any leading 'ask'/'tell me'/'explain' prefix
    so the LLM sees a clean question. Returns an empty string for empty
    input. Callers should already have established Intent.ASK.
    """
    stripped = _WAKE_PHRASE.sub("", utterance or "").strip()
    return _ASK_PREFIX.sub("", stripped).strip()
