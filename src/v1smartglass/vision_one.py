"""Thin async client for the Trend Vision One v3 API.

Covers only the endpoints we need:
  - GET /v3.0/workbench/alerts          (latest workbench alerts)
  - GET /v3.0/asrm/highRiskUsers        (top risky users)
  - GET /v3.0/asrm/highRiskDevices      (top risky devices)

Docs: https://automation.trendmicro.com/xdr/api-v3
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from .config import SEVERITY_ORDER, VisionOneConfig


@dataclass(slots=True)
class Alert:
    id: str
    model: str
    severity: str
    score: int
    created_at: datetime
    impacted_entities: list[str]


@dataclass(slots=True)
class RiskEntity:
    name: str
    score: int
    kind: str  # "user" or "device"


class VisionOneClient:
    """Async client. Use as `async with VisionOneClient(cfg) as c: ...`."""

    def __init__(self, cfg: VisionOneConfig, *, client: httpx.AsyncClient | None = None):
        self._cfg = cfg
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            base_url=cfg.base_url,
            headers={
                "Authorization": f"Bearer {cfg.api_key}",
                "Accept": "application/json",
                "User-Agent": "v1smartglass/0.1",
            },
            timeout=httpx.Timeout(30.0, connect=10.0),
        )

    async def __aenter__(self) -> "VisionOneClient":
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def fetch_alerts(self) -> list[Alert]:
        start = datetime.now(timezone.utc) - timedelta(minutes=self._cfg.lookback_minutes)
        params = {
            "startDateTime": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "orderBy": "createdDateTime desc",
            "top": 50,
        }
        data = await self._get("/v3.0/workbench/alerts", params=params)
        min_rank = SEVERITY_ORDER[self._cfg.min_severity]
        alerts: list[Alert] = []
        for item in data.get("items", []):
            severity = str(item.get("severity", "low")).lower()
            if SEVERITY_ORDER.get(severity, 0) < min_rank:
                continue
            alerts.append(
                Alert(
                    id=str(item.get("id", "")),
                    model=str(item.get("model") or item.get("alertName") or "alert"),
                    severity=severity,
                    score=int(item.get("score") or 0),
                    created_at=_parse_dt(item.get("createdDateTime")),
                    impacted_entities=_entity_names(item.get("impactScope") or {}),
                )
            )
        return alerts

    async def fetch_top_risky_users(self, top_n: int) -> list[RiskEntity]:
        return await self._fetch_risk("/v3.0/asrm/highRiskUsers", "user", top_n)

    async def fetch_top_risky_devices(self, top_n: int) -> list[RiskEntity]:
        return await self._fetch_risk("/v3.0/asrm/highRiskDevices", "device", top_n)

    async def _fetch_risk(self, path: str, kind: str, top_n: int) -> list[RiskEntity]:
        data = await self._get(path, params={"top": max(top_n, 10), "orderBy": "riskScore desc"})
        results: list[RiskEntity] = []
        for item in data.get("items", []):
            name = item.get("name") or item.get("userPrincipalName") or item.get("endpointName") or "?"
            results.append(RiskEntity(name=str(name), score=int(item.get("riskScore") or 0), kind=kind))
        return results[:top_n]

    async def _get(self, path: str, *, params: dict[str, Any]) -> dict[str, Any]:
        resp = await self._client.get(path, params=params)
        resp.raise_for_status()
        return resp.json()


def _parse_dt(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    if not value:
        return datetime.now(timezone.utc)
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _entity_names(scope: dict[str, Any]) -> list[str]:
    names: list[str] = []
    for bucket in ("users", "accounts"):
        for entry in scope.get(bucket) or []:
            if n := entry.get("name") or entry.get("userPrincipalName"):
                names.append(str(n))
    for entry in scope.get("entities") or scope.get("desktops") or []:
        if n := entry.get("entityValue") or entry.get("name"):
            names.append(str(n))
    return names
