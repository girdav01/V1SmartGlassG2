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
    # Names advertised by each G2 temple. Defaults match Even Realities' G2
    # naming scheme; check the LightOn / Even app to find yours if they differ.
    left_name: str = "Even G2_L"
    right_name: str = "Even G2_R"
    max_lines: int = Field(default=5, ge=1, le=8)
    line_chars: int = Field(default=32, ge=16, le=48)


class AppConfig(BaseModel):
    refresh_seconds: int = Field(default=60, ge=15, le=3600)
    top_n: int = Field(default=3, ge=1, le=10)
    dry_run: bool = False


class AsrConfig(BaseModel):
    # Set to false to skip host-mic transcription and use the wake-cycle
    # fallback (each wake rotates through intents).
    enabled: bool = True
    # faster-whisper model. tiny.en (~75MB) is plenty for short commands;
    # base.en (~140MB) is more robust to background noise.
    model: str = "tiny.en"
    device: str = "cpu"        # "cpu" | "cuda" | "auto"
    compute_type: str = "int8"  # int8 is fast and small on CPU
    language: str = "en"
    # How long to record from the host mic after each wake event.
    record_seconds: float = Field(default=4.0, ge=1.0, le=15.0)
    sample_rate: int = 16000
    # sounddevice input device index/name; null = system default mic.
    mic_device: int | str | None = None


class McpServerConfig(BaseModel):
    # Friendly name (shown in logs); also used by the LLM to disambiguate tools.
    name: str
    # 'stdio' (subprocess) or 'http' (Streamable HTTP / SSE). stdio is the most
    # common transport — Docker images and `uvx` scripts both speak it.
    transport: Literal["stdio", "http"] = "stdio"
    # stdio params
    command: str | None = None
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    # http params
    url: str | None = None
    # Optional per-server tool allowlist; when set, only these tools are
    # advertised to the LLM (smaller prompts, fewer wrong-tool calls).
    tools: list[str] = Field(default_factory=list)
    enabled: bool = True


class LlmConfig(BaseModel):
    enabled: bool = False
    # OpenAI-compatible Chat Completions endpoint. For Ollama via Tailscale:
    #   http://100.x.y.z:11434/v1
    # For LMStudio:
    #   http://host.docker.internal:1234/v1
    # For OpenAI:
    #   https://api.openai.com/v1
    base_url: str = "http://localhost:11434/v1"
    # Any non-empty string for local servers; real key for SaaS.
    api_key: str = "ollama"
    model: str = "qwen2.5:14b-instruct"
    # Hard ceiling on the rendered answer (5 HUD lines x 32 chars).
    max_chars: int = 160
    # Max LLM-tool iterations per ASK; keeps runaway agents bounded.
    max_turns: int = 6
    timeout_seconds: float = 30.0
    system_prompt: str | None = None  # overrides built-in default


class NewsConfig(BaseModel):
    enabled: bool = False
    # How long to keep a fetched feed in memory before re-pulling.
    cache_ttl_seconds: int = Field(default=600, ge=30, le=86400)
    # Max items per source rendered on the HUD.
    top_n: int = Field(default=5, ge=1, le=20)
    # If true and llm.enabled, each item is summarised by the LLM before
    # rendering. Falls back to the feed's own description if false or if
    # the LLM is unavailable.
    summarize: bool = True
    # Per-fetch timeout for any one feed URL.
    fetch_timeout_seconds: float = 10.0
    # Headline + summary character budgets when feeding to the LLM.
    headline_max_chars: int = 64
    summary_max_chars: int = 96
    # RSS feed URLs grouped by source. Each list maps to a voice intent:
    #   security    -> "Hey Even, security news"
    #   hacker_news -> "Hey Even, hacker news"
    #   medium      -> "Hey Even, my medium"
    sources: dict[str, list[str]] = Field(default_factory=dict)


class Settings(BaseModel):
    vision_one: VisionOneConfig
    glasses: GlassesConfig = GlassesConfig()
    app: AppConfig = AppConfig()
    asr: AsrConfig = AsrConfig()
    llm: LlmConfig = LlmConfig()
    mcp_servers: list[McpServerConfig] = Field(default_factory=list)
    news: NewsConfig = NewsConfig()

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
