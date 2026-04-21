from datetime import datetime, timezone

from v1smartglass.config import GlassesConfig
from v1smartglass.formatter import build_frames
from v1smartglass.vision_one import Alert, RiskEntity


def _alert(model: str, severity: str, who: str) -> Alert:
    return Alert(
        id=model,
        model=model,
        severity=severity,
        score=50,
        created_at=datetime(2026, 4, 21, tzinfo=timezone.utc),
        impacted_entities=[who],
    )


def test_alert_frame_ranks_critical_first() -> None:
    alerts = [
        _alert("Phishing", "medium", "alice@corp"),
        _alert("Ransomware", "critical", "bob@corp"),
    ]
    frames = build_frames(alerts, [], [], GlassesConfig(), top_n=3)
    alert_frame = frames[0]
    assert alert_frame.title.startswith("V1 ALERTS (2)")
    assert "Ransomware" in alert_frame.lines[0]
    assert "bob@corp" in alert_frame.lines[0]


def test_risk_frames_respect_top_n() -> None:
    users = [RiskEntity(name=f"user{i}@corp", score=100 - i, kind="user") for i in range(5)]
    devices = [RiskEntity(name=f"host-{i}", score=80 - i, kind="device") for i in range(5)]
    frames = build_frames([], users, devices, GlassesConfig(), top_n=2)

    _, users_frame, devices_frame = frames
    assert users_frame.title == "TOP RISKY USERS"
    assert users_frame.lines[0].startswith("1. user0@corp")
    assert users_frame.lines[1].startswith("2. user1@corp")
    assert devices_frame.title == "TOP RISKY DEVICES"
    assert devices_frame.lines[0].startswith("1. host-0")


def test_empty_alerts_shows_placeholder() -> None:
    frames = build_frames([], [], [], GlassesConfig(), top_n=3)
    assert frames[0].lines == ["No alerts in window."]


def test_long_entity_truncated() -> None:
    alerts = [_alert("VeryLongSuspiciousBehaviorModel", "high", "really.long.user.principal.name@corp.example.com")]
    frames = build_frames(alerts, [], [], GlassesConfig(line_chars=24), top_n=3)
    assert all(len(line) <= 24 for line in frames[0].lines)
