from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, field_validator

Region = Literal["us", "eu", "jp", "sg", "au", "in", "uae"]

REGION_HOSTS: dict[str, str] = {
    "us": "api.xdr.trendmicro.com",
    "eu": "api.eu.xdr.trendmicro.com",
    "jp": "api.xdr.trendmicro.co.jp",
    "sg": "api.sg.xdr.trendmicro.com",
    "au": "api.au.xdr.trendmicro.com",
    "in": "api.in.xdr.trendmicro.com",
    "uae": "api.uae.xdr.trendmicro.com",
}

Severity = Literal["low", "medium", "high", "critical"]
SEVERITY_ORDER: dict[str, int] = {"low": 0, "medium": 1, "high": 2, "critical": 3}


class VisionOneConfig(BaseModel):
    api_key: str
    region: Region = "us"
    lookback_minutes: int = Field(default=60, ge=5, le=1440)
    min_severity: Severity = "medium"

    @property
    def base_url(self) -> str:
        return f"https://{REGION_HOSTS[self.region]}"


class GlassesConfig(BaseModel):
    device_name: str | None = None
    max_lines: int = Field(default=5, ge=1, le=8)
    line_chars: int = Field(default=32, ge=16, le=48)


class AppConfig(BaseModel):
    refresh_seconds: int = Field(default=60, ge=15, le=3600)
    top_n: int = Field(default=3, ge=1, le=10)
    dry_run: bool = False


class Settings(BaseModel):
    vision_one: VisionOneConfig
    glasses: GlassesConfig = GlassesConfig()
    app: AppConfig = AppConfig()

    @field_validator("vision_one")
    @classmethod
    def _key_present(cls, v: VisionOneConfig) -> VisionOneConfig:
        if not v.api_key or v.api_key == "REPLACE_ME":
            raise ValueError("vision_one.api_key is required")
        return v


def load(path: str | os.PathLike[str] | None = None) -> Settings:
    """Load settings from YAML, with V1SG_* env vars overriding."""
    data: dict = {}
    if path is None:
        for candidate in ("config.yaml", "config.local.yaml"):
            if Path(candidate).exists():
                path = candidate
                break
    if path is not None:
        data = yaml.safe_load(Path(path).read_text()) or {}

    data.setdefault("vision_one", {})
    if env_key := os.getenv("V1SG_API_KEY"):
        data["vision_one"]["api_key"] = env_key
    if env_region := os.getenv("V1SG_REGION"):
        data["vision_one"]["region"] = env_region

    return Settings.model_validate(data)
