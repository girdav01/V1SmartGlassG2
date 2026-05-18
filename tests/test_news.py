from datetime import datetime, timezone

import httpx
import pytest

from v1smartglass.config import GlassesConfig, NewsConfig
from v1smartglass.formatter import news_frames
from v1smartglass.news import Article, NewsService, _shrink, _strip_html


_HN_RSS = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
  <title>Hacker News</title>
  <link>https://news.ycombinator.com/</link>
  <description>Links for the intellectually curious</description>
  <item>
    <title>Show HN: New cool cryptography library</title>
    <link>https://example.com/crypto</link>
    <pubDate>Mon, 18 May 2026 09:00:00 +0000</pubDate>
    <description>&lt;p&gt;A small audit-friendly library.&lt;/p&gt;</description>
  </item>
  <item>
    <title>Critical vuln in widget framework</title>
    <link>https://example.com/vuln</link>
    <pubDate>Mon, 18 May 2026 08:30:00 +0000</pubDate>
    <description>RCE via crafted JSON payload.</description>
  </item>
  <item>
    <title>Old story</title>
    <link>https://example.com/old</link>
    <pubDate>Sun, 17 May 2026 06:00:00 +0000</pubDate>
    <description>Stale.</description>
  </item>
</channel></rss>
"""


def _mock_transport() -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/hn"):
            return httpx.Response(200, content=_HN_RSS)
        if request.url.path.endswith("/broken"):
            return httpx.Response(500)
        return httpx.Response(404)
    return httpx.MockTransport(handler)


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=_mock_transport())


def _cfg(**overrides: object) -> NewsConfig:
    base = {
        "enabled": True,
        "summarize": False,
        "top_n": 5,
        "sources": {"hacker_news": ["https://hn.example/hn"]},
    }
    base.update(overrides)
    return NewsConfig(**base)


@pytest.mark.asyncio
async def test_fetch_parses_rss_and_sorts_newest_first() -> None:
    async with NewsService(_cfg(), http_client=_client()) as svc:
        items = await svc.fetch("hacker_news")
    assert [a.title for a in items][:3] == [
        "Show HN: New cool cryptography library",
        "Critical vuln in widget framework",
        "Old story",
    ]
    assert all(isinstance(a.published_at, datetime) for a in items)
    # fallback summary populated from raw_summary when summarize=False
    assert "audit-friendly" in items[0].summary


@pytest.mark.asyncio
async def test_fetch_respects_top_n() -> None:
    async with NewsService(_cfg(top_n=2), http_client=_client()) as svc:
        items = await svc.fetch("hacker_news")
    assert len(items) == 2


@pytest.mark.asyncio
async def test_partial_failures_dont_break_batch() -> None:
    cfg = _cfg(sources={"hacker_news": ["https://hn.example/hn", "https://hn.example/broken"]})
    async with NewsService(cfg, http_client=_client()) as svc:
        items = await svc.fetch("hacker_news")
    assert len(items) >= 2  # the working feed still got parsed


@pytest.mark.asyncio
async def test_cache_hit_skips_refetch() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(200, content=_HN_RSS)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    async with NewsService(_cfg(), http_client=client) as svc:
        await svc.fetch("hacker_news")
        await svc.fetch("hacker_news")
    assert calls["n"] == 1


@pytest.mark.asyncio
async def test_summariser_invoked_when_enabled() -> None:
    seen: list[tuple[str, str]] = []

    async def summarise(title: str, snippet: str) -> str:
        seen.append((title, snippet))
        return f"AI: {title[:20]}"

    async with NewsService(
        _cfg(summarize=True), http_client=_client(), summariser=summarise,
    ) as svc:
        items = await svc.fetch("hacker_news")
    assert all(a.summary.startswith("AI: ") for a in items)
    assert len(seen) == len(items)


@pytest.mark.asyncio
async def test_summariser_failure_falls_back_to_raw_summary() -> None:
    async def fail(title: str, snippet: str) -> str:
        raise RuntimeError("LLM down")

    async with NewsService(
        _cfg(summarize=True), http_client=_client(), summariser=fail,
    ) as svc:
        items = await svc.fetch("hacker_news")
    assert all(a.summary for a in items)
    # cleanly fell back to the feed snippet text
    assert "AI:" not in items[0].summary


@pytest.mark.asyncio
async def test_empty_source_returns_empty_list() -> None:
    async with NewsService(_cfg(sources={"hacker_news": []}), http_client=_client()) as svc:
        items = await svc.fetch("hacker_news")
    assert items == []


def test_strip_html_handles_tags_and_entities() -> None:
    assert _strip_html("<p>foo &amp; bar</p>") == "foo & bar"
    assert _strip_html("") == ""


def test_shrink_truncates_with_ellipsis() -> None:
    assert _shrink("a" * 50, 20).endswith("…")
    assert len(_shrink("a" * 50, 20)) == 20
    assert _shrink("short", 20) == "short"


def _article(title: str, summary: str = "summary text") -> Article:
    return Article(
        title=title,
        link="https://x",
        source="src",
        published_at=datetime.now(timezone.utc),
        raw_summary="",
        summary=summary,
    )


def test_news_frames_layout_digest_plus_cards() -> None:
    g = GlassesConfig(line_chars=32, max_lines=5)
    articles = [_article(f"Headline {i}", f"summary {i}") for i in range(5)]
    frames = news_frames(articles, "Hacker News", g)

    assert frames[0].title == "HACKER NEWS"
    # Digest: 3 numbered headlines
    assert frames[0].lines[0].startswith("1.")
    assert frames[0].lines[1].startswith("2.")
    assert frames[0].lines[2].startswith("3.")

    # One detail frame per article
    assert len(frames) == 1 + 5
    assert frames[1].title == "HACKER NEWS 1/5"
    assert any("Headline 0" in line for line in frames[1].lines)
    assert any("summary 0" in line for line in frames[1].lines)


def test_news_frames_empty_articles_shows_placeholder() -> None:
    g = GlassesConfig(line_chars=32, max_lines=5)
    frames = news_frames([], "Medium", g)
    assert len(frames) == 1
    assert frames[0].title == "MEDIUM"
    assert any("No items" in line for line in frames[0].lines)
