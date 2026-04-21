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
    UNKNOWN = "unknown"


# Each intent has a list of regex patterns. We strip the wake phrase first,
# then try each pattern in order.
_WAKE_PHRASE = re.compile(r"^\s*(hey|hi|ok)\s+even[,\s]+", re.IGNORECASE)

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
    for intent, patterns in _PATTERNS.items():
        if any(p.search(stripped) for p in patterns):
            return intent
    return Intent.UNKNOWN
