import httpx
import pytest
import respx

from v1smartglass.config import VisionOneConfig
from v1smartglass.vision_one import VisionOneClient


@pytest.fixture
def cfg() -> VisionOneConfig:
    return VisionOneConfig(api_key="test-key", region="eu", lookback_minutes=30, min_severity="medium")


@respx.mock
async def test_fetch_alerts_filters_by_severity(cfg: VisionOneConfig) -> None:
    payload = {
        "items": [
            {
                "id": "a1",
                "model": "Ransomware",
                "severity": "critical",
                "score": 90,
                "createdDateTime": "2026-04-21T12:00:00Z",
                "impactScope": {"users": [{"name": "alice@corp"}]},
            },
            {
                "id": "a2",
                "model": "Low-fi signal",
                "severity": "low",
                "score": 10,
                "createdDateTime": "2026-04-21T12:05:00Z",
                "impactScope": {},
            },
        ]
    }
    route = respx.get("https://api.eu.xdr.trendmicro.com/v3.0/workbench/alerts").mock(
        return_value=httpx.Response(200, json=payload)
    )

    async with VisionOneClient(cfg) as client:
        alerts = await client.fetch_alerts()

    assert route.called
    request = route.calls.last.request
    assert request.headers["authorization"] == "Bearer test-key"
    assert [a.id for a in alerts] == ["a1"]
    assert alerts[0].impacted_entities == ["alice@corp"]


@respx.mock
async def test_fetch_top_risky_users_limits_results(cfg: VisionOneConfig) -> None:
    payload = {"items": [{"name": f"u{i}", "riskScore": 100 - i} for i in range(5)]}
    respx.get("https://api.eu.xdr.trendmicro.com/v3.0/asrm/highRiskUsers").mock(
        return_value=httpx.Response(200, json=payload)
    )
    async with VisionOneClient(cfg) as client:
        users = await client.fetch_top_risky_users(top_n=2)
    assert [u.name for u in users] == ["u0", "u1"]
    assert users[0].score == 100


@respx.mock
async def test_http_error_raises(cfg: VisionOneConfig) -> None:
    respx.get("https://api.eu.xdr.trendmicro.com/v3.0/workbench/alerts").mock(
        return_value=httpx.Response(401, json={"error": "unauthorized"})
    )
    async with VisionOneClient(cfg) as client:
        with pytest.raises(httpx.HTTPStatusError):
            await client.fetch_alerts()
