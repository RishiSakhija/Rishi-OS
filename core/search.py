"""Shared search tool (BYOK, with a free fallback).

`web_search` uses Tavily when `TAVILY_API_KEY` is set, and otherwise falls back
to free, keyless sources so the system still works on a zero budget:

    HackerNews Algolia API   (JSON, no key)
    Reddit search JSON       (JSON, no key)
    Google News RSS          (Atom/RSS via feedparser, no key)

Results are de-duplicated against the datahouse (`db.is_duplicate`) so the same
URL is never fed to a model twice, and every search is recorded in the `usage`
table as `tavily` or `free_search`.

Plain code only apart from the HTTP calls -- no model is involved here.
"""

from __future__ import annotations

import re
from urllib.parse import urlencode

import requests

from . import config, db

TAVILY_URL = "https://api.tavily.com/search"
HN_URL = "https://hn.algolia.com/api/v1/search"
REDDIT_URL = "https://www.reddit.com/search.json"
NEWS_URL = "https://news.google.com/rss/search"

USER_AGENT = "Rishi-OS/1.0 (+https://github.com/RishiSakhija/Rishi-OS)"
MAX_SNIPPET_CHARS = 400
_WS = re.compile(r"\s+")


class SearchError(RuntimeError):
    """Raised only by the individual source helpers; `web_search` never raises."""


def _clean(text: str | None, limit: int = MAX_SNIPPET_CHARS) -> str:
    flat = _WS.sub(" ", text or "").strip()
    return flat[:limit].rstrip()


def _result(title: str, url: str, snippet: str, source: str) -> dict:
    return {
        "title": _clean(title, 200),
        "url": (url or "").strip(),
        "snippet": _clean(snippet),
        "source": source,
    }


# ---------------------------------------------------------------------------
# Paid / BYOK source
# ---------------------------------------------------------------------------
def _tavily(query: str, max_results: int) -> list[dict]:
    response = requests.post(
        TAVILY_URL,
        json={
            "api_key": config.TAVILY_API_KEY,
            "query": query,
            "max_results": max_results,
            "search_depth": "basic",
        },
        timeout=config.HTTP_TIMEOUT,
    )
    response.raise_for_status()
    payload = response.json()
    return [
        _result(item.get("title", ""), item.get("url", ""), item.get("content", ""), "tavily")
        for item in payload.get("results", [])
    ]


# ---------------------------------------------------------------------------
# Free / keyless sources
# ---------------------------------------------------------------------------
def _hackernews(query: str, max_results: int) -> list[dict]:
    response = requests.get(
        HN_URL,
        params={"query": query, "tags": "story", "hitsPerPage": max_results},
        headers={"User-Agent": USER_AGENT},
        timeout=config.HTTP_TIMEOUT,
    )
    response.raise_for_status()
    hits = response.json().get("hits", [])
    out = []
    for hit in hits:
        url = hit.get("url") or (
            f"https://news.ycombinator.com/item?id={hit.get('objectID')}"
            if hit.get("objectID")
            else ""
        )
        out.append(
            _result(hit.get("title", ""), url, hit.get("story_text") or "", "hackernews")
        )
    return out


def _reddit(query: str, max_results: int) -> list[dict]:
    response = requests.get(
        REDDIT_URL,
        params={"q": query, "limit": max_results, "sort": "relevance", "t": "month"},
        headers={"User-Agent": USER_AGENT},
        timeout=config.HTTP_TIMEOUT,
    )
    response.raise_for_status()
    children = response.json().get("data", {}).get("children", [])
    out = []
    for child in children:
        data = child.get("data", {})
        url = data.get("url") or (
            "https://www.reddit.com" + data.get("permalink", "")
            if data.get("permalink")
            else ""
        )
        out.append(
            _result(data.get("title", ""), url, data.get("selftext") or "", "reddit")
        )
    return out


def _google_news(query: str, max_results: int) -> list[dict]:
    """RSS/Atom. feedparser is optional -- absence just disables this source."""
    try:
        import feedparser  # local import: optional dependency
    except ImportError:
        return []

    url = NEWS_URL + "?" + urlencode(
        {"q": query, "hl": "en-US", "gl": "US", "ceid": "US:en"}
    )
    feed = feedparser.parse(url, request_headers={"User-Agent": USER_AGENT})
    out = []
    for entry in (getattr(feed, "entries", None) or [])[:max_results]:
        out.append(
            _result(
                getattr(entry, "title", ""),
                getattr(entry, "link", ""),
                getattr(entry, "summary", ""),
                "google_news",
            )
        )
    return out


def _free_search(query: str, max_results: int) -> list[dict]:
    """Merge the keyless sources, round-robin, so no single source dominates."""
    buckets: list[list[dict]] = []
    for helper in (_hackernews, _google_news, _reddit):
        try:
            buckets.append(helper(query, max_results))
        except Exception:  # noqa: BLE001 - one dead source must not kill search
            buckets.append([])

    merged: list[dict] = []
    for index in range(max_results):
        for bucket in buckets:
            if index < len(bucket):
                merged.append(bucket[index])
    return merged


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def web_search(query: str, max_results: int = 5, *, agent: str | None = None) -> list[dict]:
    """Search the web and return de-duplicated results.

    Returns a list of `{title, url, snippet, source}`. Never raises: on total
    failure it returns an empty list so the caller can still make its one model
    call with whatever context it already had (AGENTS.md Rule 5).
    """
    query = (query or "").strip()
    if not query:
        return []

    provider = "free_search"
    results: list[dict] = []

    if config.TAVILY_API_KEY:
        try:
            results = _tavily(query, max_results)
            if results:
                provider = "tavily"
        except Exception:  # noqa: BLE001 - fall through to the free sources
            results = []

    if not results:
        provider = "free_search"
        results = _free_search(query, max_results)

    fresh = _dedupe(results, max_results)
    _record_usage(agent, provider, query, fresh)
    return fresh


def _dedupe(results: list[dict], max_results: int) -> list[dict]:
    """Drop results we have already seen, by URL, and drop intra-batch repeats."""
    fresh: list[dict] = []
    seen: set[str] = set()

    for item in results:
        url = (item.get("url") or "").strip()
        if not url or url in seen:
            continue
        seen.add(url)
        try:
            if db.is_duplicate(url=url):
                continue
        except Exception:  # noqa: BLE001 - if we cannot check, keep the result
            pass
        fresh.append(item)
        if len(fresh) >= max_results:
            break
    return fresh


def _record_usage(agent: str | None, provider: str, query: str, fresh: list[dict]) -> None:
    """Best-effort ledger write. Never raises -- accounting is not critical."""
    try:
        db.record_usage(
            agent=agent or "research_agent",
            provider=provider,
            model="search",
            calls=1,
            chars_in=len(query),
            chars_out=sum(len(r.get("snippet") or "") for r in fresh),
        )
    except Exception:  # noqa: BLE001
        pass


def as_prompt_block(results: list[dict]) -> str:
    """Render results as a compact prompt block, trimmed to the input ceiling."""
    if not results:
        return "(no fresh web results available)"

    lines = []
    for item in results:
        lines.append(
            f"- {item.get('title', '')} [{item.get('source', '')}]\n"
            f"  {item.get('url', '')}\n"
            f"  {item.get('snippet', '')}"
        )
    text, _ = config.trim("\n".join(lines))
    return text
