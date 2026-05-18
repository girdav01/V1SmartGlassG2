"""News feed ingestion: pulls RSS/Atom feeds, optionally LLM-summarises each
item, caches per source for the configured TTL.

The intent → source mapping is owned by the App: NEWS_HACKER pulls from
`sources["hacker_news"]`, NEWS_SECURITY from `sources["security"]`, etc.
Each list can hold any number of feed URLs; results are merged and ranked
by published timestamp (newest first).

Feeds are parsed in a thread executor because `feedparser` is sync — RSS
parsing is fast (<50ms typical) but we don't want to block the event loop
while three feeds run in parallel.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

import httpx

from .config import NewsConfig

log = logging.getLogger(__name__)

# Stable source labels used in voice intents, frame titles, and cache keys.
SOURCE_HACKER = "hacker_news"
SOURCE_SECURITY = "security"
SOURCE_MEDIUM = "medium"


@dataclass
class Article:
    title: str
    link: str
    source: str          # e.g. "Krebs", "Hacker News", "Medium"
    published_at: datetime
    raw_summary: str     # the feed's own summary/description (may be HTML)
    summary: str = ""    # LLM-generated short summary; empty until populated


@dataclass
class _CacheEntry:
    articles: list[Article]
    fetched_at: float = field(default_factory=time.monotonic)


class NewsService:
    """Per-source feed fetcher + LLM-summariser with a TTL cache.

    The summariser is optional and pluggable: pass any async callable with
    signature ``(title: str, snippet: str) -> str`` to `__init__`. We use
    a duck-typed callable rather than importing LlmHost to keep this module
    free of an `[llm]` dependency at import time.
    """

    def __init__(
        self,
        cfg: NewsConfig,
        *,
        summariser: "_Summariser | None" = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._cfg = cfg
        self._summariser = summariser
        self._client = http_client
        self._owns_client = http_client is None
        self._cache: dict[str, _CacheEntry] = {}
        self._fetch_locks: dict[str, asyncio.Lock] = {}

    async def __aenter__(self) -> "NewsService":
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=self._cfg.fetch_timeout_seconds,
                follow_redirects=True,
                headers={"User-Agent": "v1smartglass-news/1.0 (+G2 HUD reader)"},
            )
        return self

    async def __aexit__(self, *exc: object) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    async def fetch(self, source: str) -> list[Article]:
        """Fetch + summarise items for `source`, honouring the TTL cache."""
        urls = self._cfg.sources.get(source, [])
        if not urls:
            return []

        cached = self._cache.get(source)
        ttl = self._cfg.cache_ttl_seconds
        if cached and (time.monotonic() - cached.fetched_at) < ttl:
            return cached.articles

        # Serialise concurrent fetches of the same source to avoid two voice
        # commands triggering parallel pulls; per-source lock keeps different
        # sources independent.
        lock = self._fetch_locks.setdefault(source, asyncio.Lock())
        async with lock:
            cached = self._cache.get(source)
            if cached and (time.monotonic() - cached.fetched_at) < ttl:
                return cached.articles

            articles = await self._fetch_urls(urls)
            articles.sort(key=lambda a: a.published_at, reverse=True)
            articles = articles[: self._cfg.top_n]

            if self._summariser is not None and self._cfg.summarize:
                await self._summarise_all(articles)
            else:
                for a in articles:
                    a.summary = _shrink(_strip_html(a.raw_summary), self._cfg.summary_max_chars)

            self._cache[source] = _CacheEntry(articles=articles)
            return articles

    async def _fetch_urls(self, urls: list[str]) -> list[Article]:
        """Pull each URL in parallel; partial failures don't break the batch."""
        if self._client is None:  # pragma: no cover - guarded by aenter
            raise RuntimeError("NewsService not entered (use 'async with').")
        coros = [self._fetch_one(url) for url in urls]
        results = await asyncio.gather(*coros, return_exceptions=True)
        articles: list[Article] = []
        for url, result in zip(urls, results):
            if isinstance(result, BaseException):
                log.warning("feed fetch failed %s: %s", url, result)
                continue
            articles.extend(result)
        return articles

    async def _fetch_one(self, url: str) -> list[Article]:
        assert self._client is not None
        resp = await self._client.get(url)
        resp.raise_for_status()
        body = resp.content
        # feedparser is synchronous; bounce it to a worker thread.
        return await asyncio.to_thread(_parse_feed, body, url)

    async def _summarise_all(self, articles: list[Article]) -> None:
        assert self._summariser is not None
        # Bound concurrency — most local LLMs choke past 3-4 parallel requests.
        sem = asyncio.Semaphore(3)

        async def run(a: Article) -> None:
            async with sem:
                snippet = _strip_html(a.raw_summary)[: 500]
                try:
                    a.summary = await self._summariser(a.title, snippet)
                except Exception as exc:  # noqa: BLE001
                    log.warning("LLM summary failed for %r: %s", a.title, exc)
                    a.summary = _shrink(snippet, self._cfg.summary_max_chars)

        await asyncio.gather(*(run(a) for a in articles))


# ----- helpers ---------------------------------------------------------------


def _parse_feed(body: bytes, url: str) -> list[Article]:
    """Synchronous feed parse. Called inside `asyncio.to_thread`."""
    import feedparser  # local import: only needed when news is enabled

    parsed = feedparser.parse(body)
    feed_title = (getattr(parsed.feed, "title", None) or url).strip()
    out: list[Article] = []
    for entry in parsed.entries:
        title = (entry.get("title") or "").strip()
        link = (entry.get("link") or "").strip()
        if not title or not link:
            continue
        published = _entry_published(entry)
        out.append(
            Article(
                title=title,
                link=link,
                source=feed_title,
                published_at=published,
                raw_summary=(entry.get("summary") or entry.get("description") or "").strip(),
            )
        )
    return out


def _entry_published(entry: object) -> datetime:
    # feedparser exposes parsed structs as `*_parsed`; fall back to "now" so
    # an entry without a timestamp still sorts deterministically (after dated
    # items).
    for attr in ("published_parsed", "updated_parsed"):
        parsed = entry.get(attr) if isinstance(entry, dict) else getattr(entry, attr, None)
        if parsed:
            try:
                return datetime(*parsed[:6], tzinfo=timezone.utc)
            except (TypeError, ValueError):
                pass
    return datetime.now(timezone.utc)


def _strip_html(text: str) -> str:
    """Cheap HTML-tag stripper. Good enough for RSS descriptions."""
    if not text:
        return ""
    import re

    no_tags = re.sub(r"<[^>]+>", " ", text)
    no_entities = (
        no_tags.replace("&nbsp;", " ")
        .replace("&amp;", "&")
        .replace("&quot;", '"')
        .replace("&#39;", "'")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
    )
    return " ".join(no_entities.split())


def _shrink(text: str, max_chars: int) -> str:
    flat = " ".join((text or "").split())
    if len(flat) <= max_chars:
        return flat
    return flat[: max_chars - 1].rstrip() + "…"


# Type alias for the summariser callable. Defined at the bottom so the docs
# above can reference it as a string forward-ref without circular issues.
from typing import Awaitable, Callable, Protocol  # noqa: E402


class _Summariser(Protocol):
    def __call__(self, title: str, snippet: str) -> Awaitable[str]: ...
