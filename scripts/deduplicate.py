"""Duplicate detection: canonical URLs, normalised headlines and similar stories.

Three layers, from strictest to loosest:
1. Same canonical URL (tracking parameters, fragments, www. and trailing slashes removed).
2. Same normalised headline (case, punctuation and " - Publisher" suffixes ignored).
3. Same story from a different publisher: high headline-token overlap AND published
   within a configurable window. Thresholds are deliberately strict so that genuinely
   different articles on the same broad topic are kept.
"""
from __future__ import annotations

import hashlib
import re
from difflib import SequenceMatcher
from typing import Any, Iterable
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from .common import parse_iso

TRACKING_PARAMS = {
    "fbclid", "gclid", "dclid", "msclkid", "mc_cid", "mc_eid", "igshid", "ref", "ref_src",
    "source", "cmpid", "cmp", "ncid", "ocid", "sr_share", "spm", "_hsenc", "_hsmi", "hsctatracking",
    "mkt_tok", "oly_anon_id", "oly_enc_id", "vero_id", "yclid", "guccounter", "smid", "sh",
}

STOPWORDS = set(
    "a an the and or but of to in on for with by from at as is are was were be been it its this that these "
    "those into over under about after before new how why what when who will can could may might says said "
    "report reports via than more most just now up out not no yes your you our we their they his her".split()
)

PUBLISHER_SUFFIX_RE = re.compile(r"\s+[-–—|]\s+[^-–—|]{2,60}$")
NON_WORD_RE = re.compile(r"[^\w\s]", re.UNICODE)


def canonical_url(url: str) -> str:
    parsed = urlparse(url.strip())
    host = (parsed.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    port = f":{parsed.port}" if parsed.port and parsed.port not in (80, 443) else ""
    query = [
        (k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=False)
        if not k.lower().startswith("utm_") and k.lower() not in TRACKING_PARAMS
    ]
    query.sort()
    path = re.sub(r"/{2,}", "/", parsed.path or "/")
    if len(path) > 1 and path.endswith("/"):
        path = path[:-1]
    return urlunparse(("https", host + port, path, "", urlencode(query), ""))


def article_id(url: str) -> str:
    return hashlib.sha1(canonical_url(url).encode("utf-8")).hexdigest()[:16]


def normalise_title(title: str, strip_publisher: bool = False) -> str:
    text = title or ""
    if strip_publisher:
        text = PUBLISHER_SUFFIX_RE.sub("", text)
    text = NON_WORD_RE.sub(" ", text.lower())
    return re.sub(r"\s+", " ", text).strip()


def title_tokens(title: str) -> set[str]:
    return {t for t in normalise_title(title).split() if t not in STOPWORDS and len(t) > 1}


def title_similarity(a: str, b: str) -> float:
    ta, tb = title_tokens(a), title_tokens(b)
    if len(ta) < 4 or len(tb) < 4:
        # Short headlines: rely on near-exact string match only.
        return 1.0 if normalise_title(a) == normalise_title(b) else 0.0
    jaccard = len(ta & tb) / len(ta | tb)
    ratio = SequenceMatcher(None, " ".join(sorted(ta)), " ".join(sorted(tb))).ratio()
    return max(jaccard, ratio - 0.25)  # sequence ratio is generous; discount it


CREDIBILITY_RANK = {"official": 3, "publication": 2, "aggregator": 1}


def _rank(article: dict[str, Any]) -> tuple:
    """Lower tuple = stronger record."""
    published = parse_iso(article.get("published_at"))
    has_analysis = 1 if (article.get("analysis") or {}).get("status") == "complete" else 0
    return (
        -has_analysis,
        -CREDIBILITY_RANK.get(article.get("credibility", "publication"), 2),
        published.timestamp() if published else float("inf"),
    )


def _within(a: dict[str, Any], b: dict[str, Any], hours: float) -> bool:
    da, db = parse_iso(a.get("published_at")), parse_iso(b.get("published_at"))
    if not da or not db:
        return False
    return abs((da - db).total_seconds()) <= hours * 3600


def _add_coverage(primary: dict[str, Any], dup: dict[str, Any]) -> None:
    covered = primary.setdefault("also_covered_by", [])
    known = {c.get("url") for c in covered} | {primary.get("url")}
    for item in [dup] + list(dup.get("also_covered_by", [])):
        if item.get("url") and item["url"] not in known:
            covered.append({"source": item.get("source"), "url": item["url"], "title": item.get("title")})
            known.add(item["url"])


def deduplicate(
    articles: Iterable[dict[str, Any]],
    similarity_threshold: float = 0.6,
    window_hours: float = 72,
) -> tuple[list[dict[str, Any]], int]:
    """Return (unique_articles, removed_count). Earlier items win ties, so pass the
    existing archive first to keep its analysis and IDs stable."""
    unique: list[dict[str, Any]] = []
    by_url: dict[str, dict[str, Any]] = {}
    by_title: dict[str, dict[str, Any]] = {}
    removed = 0

    for art in articles:
        curl = canonical_url(art["url"])
        ntitle = normalise_title(art.get("title", ""), strip_publisher=art.get("credibility") == "aggregator")
        match = by_url.get(curl) or (by_title.get(ntitle) if ntitle else None)
        if match is None:
            for existing in unique:
                if existing.get("source") == art.get("source"):
                    continue  # same publisher re-titling is handled by URL/title checks
                if _within(existing, art, window_hours) and \
                        title_similarity(existing.get("title", ""), art.get("title", "")) >= similarity_threshold:
                    match = existing
                    break
        if match is None:
            art["canonical_url"] = curl
            unique.append(art)
            by_url[curl] = art
            if ntitle:
                by_title[ntitle] = art
            continue

        removed += 1
        # Keep the stronger record as primary (analysed > official > earlier).
        if _rank(art) < _rank(match) and match.get("canonical_url") != curl:
            idx = unique.index(match)
            art["canonical_url"] = curl
            art.setdefault("also_covered_by", [])
            _add_coverage(art, match)
            match.pop("also_covered_by", None)
            unique[idx] = art
            by_url[curl] = art
            by_url[match["canonical_url"]] = art
            if ntitle:
                by_title[ntitle] = art
        elif match.get("canonical_url") != curl:
            _add_coverage(match, art)
            by_url[curl] = match
    return unique, removed
