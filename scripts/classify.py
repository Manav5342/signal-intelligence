"""Rule-based relevance, category, region and priority.

These rules run on every article (and are the fallback when AI analysis is unavailable).
When AI analysis succeeds, its category/region/priority are used if they pass validation.
"""
from __future__ import annotations

import re
from datetime import datetime
from functools import lru_cache
from typing import Any

from .common import parse_iso, utc_now

PRIORITIES = ("High", "Medium", "Low")
REGIONS = ("Global", "India")


@lru_cache(maxsize=2048)
def _pattern(term: str) -> re.Pattern:
    escaped = re.escape(term.lower())
    # Word boundaries for alphanumeric edges; symbols like "₹" match as-is.
    left = r"(?<![\w])" if term[:1].isalnum() else ""
    right = r"(?![\w])" if term[-1:].isalnum() else ""
    return re.compile(left + escaped + right)


def matched_terms(text: str, terms: list[str]) -> list[str]:
    low = (text or "").lower()
    return [t for t in terms if _pattern(t).search(low)]


def category_scores(article: dict[str, Any], config: dict[str, Any]) -> dict[str, int]:
    title = article.get("title", "")
    body = " ".join([article.get("content", ""), " ".join(article.get("feed_tags", []))])
    scores = {}
    for key, cat in config["categories"].items():
        score = 3 * len(matched_terms(title, cat["keywords"])) + len(matched_terms(body, cat["keywords"]))
        if article.get("category_hint") == key:
            score += 2 if article.get("focused_source") else 1
        scores[key] = score
    return scores


def relevance(article: dict[str, Any], config: dict[str, Any]) -> tuple[bool, str, dict[str, int]]:
    scores = category_scores(article, config)
    hint = article.get("category_hint")
    best = max(scores, key=lambda k: (scores[k], k == hint))
    threshold = config["settings"].get("min_relevance_score", 3)
    keyword_score = scores[best] - (2 if article.get("focused_source") and best == hint else 1 if best == hint else 0)
    # Focused feeds are on-topic by construction but still need at least one keyword hit
    # (or a hint bonus with a short excerpt, common for official blogs).
    if article.get("focused_source"):
        is_relevant = keyword_score >= 1 or not article.get("content")
    else:
        is_relevant = scores[best] >= threshold
    return is_relevant, best, scores


def detect_region(article: dict[str, Any], config: dict[str, Any]) -> tuple[str, str]:
    """India only when geographic relevance is established, not because an Indian
    company is named. Requires an India term in the headline, or 2+ distinct India
    terms in the body."""
    terms = config.get("india_terms", [])
    in_title = matched_terms(article.get("title", ""), terms)
    in_body = set(matched_terms(article.get("content", ""), terms)) - set(in_title)
    if in_title:
        return "India", f"Headline references India-specific context ({', '.join(in_title[:3])})."
    if len(in_body) >= 2:
        return "India", f"Article body references Indian market context ({', '.join(sorted(in_body)[:3])})."
    if article.get("region_hint") == "India":
        return "Global", "Indian publisher, but no India-specific market, regulatory or geographic focus was detected."
    return "Global", "No India-specific market, regulatory or geographic focus detected."


def heuristic_priority(article: dict[str, Any], config: dict[str, Any], best_score: int, now: datetime | None = None) -> tuple[str, int]:
    now = now or utc_now()
    impact = matched_terms(article.get("title", ""), config.get("high_impact_terms", []))
    score = min(best_score, 8) + 3 * len(impact)
    score += {"official": 3, "publication": 1, "aggregator": 0}.get(article.get("credibility"), 0)
    published = parse_iso(article.get("published_at"))
    if published and (now - published).total_seconds() < 24 * 3600:
        score += 2
    if score >= 12:
        return "High", score
    if score >= 6:
        return "Medium", score
    return "Low", score


def classify(article: dict[str, Any], config: dict[str, Any], now: datetime | None = None) -> dict[str, Any] | None:
    """Annotate an article in place; return None if it isn't relevant."""
    is_relevant, best, scores = relevance(article, config)
    if not is_relevant:
        return None
    article["category"] = best
    article["category_label"] = config["categories"][best]["label"]
    article["region"], article["region_reason"] = detect_region(article, config)
    article["priority"], article["priority_score"] = heuristic_priority(article, config, scores[best], now)
    article["classification"] = "rules"
    return article


PRIORITY_WEIGHT = {"High": 3, "Medium": 2, "Low": 1}
