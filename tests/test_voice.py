import pytest

from v1smartglass.voice import Intent, extract_ask_query, parse_intent


@pytest.mark.parametrize(
    "utterance, expected",
    [
        ("Hey Even VisionOne alerts", Intent.ALERTS),
        ("hey even, vision one alerts please", Intent.ALERTS),
        ("Hey Even V1 alerts", Intent.ALERTS),
        ("Hey Even, alerts on Vision One", Intent.ALERTS),
        ("Hey Even Vision One top risk", Intent.TOP_RISK),
        ("Hey Even, top risky users", Intent.TOP_RISK),
        ("Hey Even risky machines", Intent.TOP_RISK),
        ("Hey Even, ask why alice is risky", Intent.ASK),
        ("Hey Even, why is alice@corp at risk", Intent.ASK),
        ("Hey Even what's the last critical alert", Intent.ASK),
        ("Hey Even, tell me about 1.2.3.4", Intent.ASK),
        ("Hey Even, explain the recent incidents", Intent.ASK),
        ("Hey Even, mumble mumble cheese", Intent.UNKNOWN),
        ("", Intent.UNKNOWN),
    ],
)
def test_parse_intent(utterance: str, expected: Intent) -> None:
    assert parse_intent(utterance) is expected


@pytest.mark.parametrize(
    "utterance, expected",
    [
        ("Hey Even, ask why alice is risky", "why alice is risky"),
        ("Hey Even why is alice@corp at risk", "is alice@corp at risk"),
        ("Hey Even, tell me about 1.2.3.4", "about 1.2.3.4"),
        ("Hey Even, what is the last critical alert", "is the last critical alert"),
        ("Hey Even, explain: recent incidents", "recent incidents"),
    ],
)
def test_extract_ask_query(utterance: str, expected: str) -> None:
    assert extract_ask_query(utterance) == expected
