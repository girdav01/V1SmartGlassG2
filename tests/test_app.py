from datetime import datetime, timezone
from typing import Any

import pytest

from v1smartglass.app import App
from v1smartglass.config import AppConfig, GlassesConfig, LlmConfig, Settings, VisionOneConfig
from v1smartglass.formatter import Frame
from v1smartglass.vision_one import Alert, RiskEntity
from v1smartglass.voice import Intent


class FakeDriver:
    def __init__(self) -> None:
        self.displayed: list[list[Frame]] = []
        self.utterances: list[str] = []

    async def connect(self) -> None: ...
    async def disconnect(self) -> None: ...

    async def display(self, frames: list[Frame]) -> None:
        self.displayed.append(frames)

    async def listen_voice(self, on_utterance: Any) -> None:
        for line in self.utterances:
            await on_utterance(line)


class FakeClient:
    async def __aenter__(self) -> "FakeClient":
        return self

    async def __aexit__(self, *exc: object) -> None: ...

    async def fetch_alerts(self) -> list[Alert]:
        return [
            Alert(
                id="a1", model="Phishing", severity="high", score=80,
                created_at=datetime.now(timezone.utc), impacted_entities=["alice@corp"],
            )
        ]

    async def fetch_top_risky_users(self, top_n: int) -> list[RiskEntity]:
        return [RiskEntity(name="alice@corp", score=95, kind="user")]

    async def fetch_top_risky_devices(self, top_n: int) -> list[RiskEntity]:
        return [RiskEntity(name="host-1", score=88, kind="device")]


@pytest.fixture
def settings() -> Settings:
    return Settings(
        vision_one=VisionOneConfig(api_key="x", region="eu"),
        glasses=GlassesConfig(),
        app=AppConfig(dry_run=True, top_n=2),
    )


async def test_voice_loop_dispatches_alerts(settings: Settings) -> None:
    driver = FakeDriver()
    driver.utterances = ["Hey Even VisionOne alerts"]
    app = App(settings, driver=driver)
    app._client = FakeClient()  # type: ignore[assignment]

    await app.run()

    # First display is the ready banner, second is the alerts frame.
    assert len(driver.displayed) == 2
    alerts_frame = driver.displayed[1][0]
    assert "Phishing" in alerts_frame.lines[0]


async def test_handle_top_risk_returns_two_frames(settings: Settings) -> None:
    app = App(settings, driver=FakeDriver())
    app._client = FakeClient()  # type: ignore[assignment]
    frames = await app.handle(Intent.TOP_RISK)
    assert [f.title for f in frames] == ["TOP RISKY USERS", "TOP RISKY DEVICES"]


class FakeLlm:
    def __init__(self, answer: str) -> None:
        self._answer = answer
        self.queries: list[str] = []

    async def __aenter__(self) -> "FakeLlm":
        return self

    async def __aexit__(self, *exc: object) -> None: ...

    async def ask(self, query: str) -> str:
        self.queries.append(query)
        return self._answer


async def test_handle_ask_uses_llm(settings: Settings) -> None:
    settings_with_llm = settings.model_copy(update={"llm": LlmConfig(enabled=True)})
    fake_llm = FakeLlm(answer="VisionOne: alice@corp risk=95 (suspicious login from RU).")

    app = App(settings_with_llm, driver=FakeDriver())
    app._client = FakeClient()  # type: ignore[assignment]
    app._llm = fake_llm  # type: ignore[assignment]
    app._pending_query = "why alice is risky"

    frames = await app.handle(Intent.ASK)
    assert fake_llm.queries == ["why alice is risky"]
    assert frames[0].title == "ASK"
    assert any("alice@corp" in line for line in frames[0].lines)


async def test_handle_ask_without_llm_returns_helpful_message(settings: Settings) -> None:
    # llm.enabled is False in the default fixture.
    app = App(settings, driver=FakeDriver())
    app._client = FakeClient()  # type: ignore[assignment]
    app._pending_query = "anything"
    frames = await app.handle(Intent.ASK)
    assert "disabled" in frames[0].lines[0].lower()
