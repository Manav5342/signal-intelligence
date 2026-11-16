"""Fetch and parse configured RSS/Atom feeds.

Only feed content that publishers syndicate is used (title, link, date, summary/content).
Article pages are not scraped. Each source is isolated: one failure is logged and the
run continues.
"""
from __future__ import annotations

import calendar
import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import quote_plus

import feedparser
import requests

from .common import clean_text, http_session, iso, is_safe_public_url, utc_now
from .deduplicate import PUBLISHER_SUFFIX_RE, article_id

LOG = logging.getLogger("signal.fetch")

GOOGLE_NEWS_LOCALES = {
    "en-US": "hl=en-US&gl=US&ceid=US:en",
    "en-IN": "hl=en-IN&gl=IN&ceid=IN:en",
    "en-GB": "hl=en-GB&gl=GB&ceid=GB:en",
}


@dataclass
class SourceResult:
    source_id: str
    name: str
    url: str
    ok: bool
    items: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None
    entries_seen: int = 0
    status_code: int | None = None


def feed_url(source: dict[str, Any]) -> str:
    if source.get("type") == "google_news":
        locale = GOOGLE_NEWS_LOCALES.get(source.get("locale", "en-US"), GOOGLE_NEWS_LOCALES["en-US"])
        return f"https://news.google.com/rss/search?q={quote_plus(source['query'])}&{locale}"
    return source["url"]


def _entry_datetime(entry: Any) -> datetime | None:
    for key in ("published_parsed", "updated_parsed", "created_parsed"):
        value = entry.get(key)
        if value:
            try:
                return datetime.fromtimestamp(calendar.timegm(value), tz=timezone.utc)
            except (OverflowError, ValueError, TypeError):
                continue
    return None


def _entry_text(entry: Any) -> str:
    parts = []
    for content in entry.get("content") or []:
        if content.get("value"):
            parts.append(content["value"])
    if not parts and entry.get("summary"):
        parts.append(entry["summary"])
    return clean_text(" ".join(parts))


def parse_feed(raw: bytes | str, source: dict[str, Any], now: datetime | None = None) -> tuple[list[dict[str, Any]], int]:
    """Parse feed bytes into normalised article dicts. Returns (items, entries_seen)."""
    now = now or utc_now()
    parsed = feedparser.parse(raw)
    if parsed.bozo and not parsed.entries:
        raise ValueError(f"Unparseable feed: {getattr(parsed, 'bozo_exception', 'unknown error')}")
    items = []
    is_aggregator = source.get("type") == "google_news"
    for entry in parsed.entries:
        link = (entry.get("link") or "").strip()
        title = clean_text(entry.get("title"))
        if not link or not title or not is_safe_public_url(link):
            continue
        published = _entry_datetime(entry)
        if published is None:
            # Never invent a date: undated entries are skipped.
            continue
        if published > now + timedelta(hours=6):
            continue  # clearly wrong future dates
        publisher = source["name"]
        full_text = _entry_text(entry)
        if is_aggregator:
            src = entry.get("source") or {}
            publisher = clean_text(src.get("title")) or "Unknown publisher"
            title = PUBLISHER_SUFFIX_RE.sub("", title).strip() or title
            # Google News summaries are just the headline + publisher; don't treat as body text.
            full_text = ""
        items.append({
            "id": article_id(link),
            "title": title,
            "url": link,
            "source": publisher,
            "source_id": source["id"],
            "via": source["name"] if is_aggregator else None,
            "credibility": source.get("credibility", "publication"),
            "published_at": iso(published),
            "collected_at": iso(now),
            "category_hint": source.get("category_hint"),
            "region_hint": source.get("region_hint", "Global"),
            "focused_source": bool(source.get("focused")),
            "content": full_text[:6000],
            "excerpt": clean_text(full_text, 300),
            "authors": [clean_text(a.get("name")) for a in entry.get("authors", []) if a.get("name")][:3],
            "feed_tags": [clean_text(t.get("term")) for t in entry.get("tags", []) if t.get("term")][:8],
        })
    return items, len(parsed.entries)


def fetch_source(source: dict[str, Any], session: requests.Session, timeout: float, now: datetime | None = None) -> SourceResult:
    url = feed_url(source)
    result = SourceResult(source_id=source["id"], name=source["name"], url=url, ok=False)
    try:
        resp = session.get(url, timeout=timeout)
        result.status_code = resp.status_code
        resp.raise_for_status()
        result.items, result.entries_seen = parse_feed(resp.content, source, now)
        result.ok = True
        LOG.info("%-28s %3d entries, %3d usable", source["id"], result.entries_seen, len(result.items))
    except Exception as exc:  # one failed source must never stop the run
        result.error = f"{type(exc).__name__}: {exc}"[:300]
        LOG.warning("Source failed: %s (%s) -> %s", source["id"], url, result.error)
    return result


def fetch_all(config: dict[str, Any], now: datetime | None = None, session: requests.Session | None = None) -> list[SourceResult]:
    session = session or http_session(config)
    timeout = config["settings"].get("request_timeout_seconds", 20)
    sources = [s for s in config["sources"] if s.get("enabled", True)]
    with ThreadPoolExecutor(max_workers=config["settings"].get("max_workers", 8)) as pool:
        return list(pool.map(lambda s: fetch_source(s, session, timeout, now), sources))


def within_freshness(item: dict[str, Any], days: float, now: datetime | None = None) -> bool:
    now = now or utc_now()
    published = datetime.fromisoformat(item["published_at"].replace("Z", "+00:00"))
    return published >= now - timedelta(days=days)
