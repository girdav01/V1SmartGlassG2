import pytest

from v1smartglass.voice import Intent, parse_intent


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
        ("Hey Even, what's the weather", Intent.UNKNOWN),
        ("", Intent.UNKNOWN),
    ],
)
def test_parse_intent(utterance: str, expected: Intent) -> None:
    assert parse_intent(utterance) is expected
