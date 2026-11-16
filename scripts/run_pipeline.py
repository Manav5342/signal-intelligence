"""Signal collection pipeline (run by GitHub Actions twice daily).

  python -m scripts.run_pipeline              # full run
  python -m scripts.run_pipeline --no-ai      # collect/classify only
  python -m scripts.run_pipeline --dry-run    # don't write files

Steps: fetch feeds -> freshness filter -> relevance/category/region/priority ->
URL validation -> deduplicate against archive -> AI analysis -> archive trim -> write.
Previously collected articles are preserved (up to settings.archive_limit).
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Any

from . import analyse_news
from .classify import PRIORITY_WEIGHT, classify, matched_terms
from .common import (NEWS_PATH, SCHEMA_VERSION, SOURCE_HEALTH_PATH, http_session, iso, load_config,
                     parse_iso, read_json, setup_logging, utc_now, write_json)
from .deduplicate import canonical_url, deduplicate
from .fetch_news import fetch_all, within_freshness
from .validate_sources import source_health_report, validate_article_url

LOG = logging.getLogger("signal.pipeline")

PUBLIC_FIELDS = (
    "id", "title", "url", "canonical_url", "source", "source_id", "via", "credibility",
    "published_at", "collected_at", "category", "category_label", "region", "region_reason",
    "priority", "priority_score", "excerpt", "companies", "topics", "also_covered_by",
    "url_check", "classification", "ai_attempts", "analysis",
)


def empty_database(config: dict[str, Any]) -> dict[str, Any]:
    return {
        "meta": {
            "schema_version": SCHEMA_VERSION,
            "project": config["project"]["name"],
            "generated_at": None,
            "last_successful_update": None,
            "archive_limit": config["settings"]["archive_limit"],
            "schedule_utc": config.get("schedule_utc", []),
            "repository": os.getenv("GITHUB_REPOSITORY"),
            "categories": {k: v["label"] for k, v in config["categories"].items()},
            "last_run": None,
        },
        "articles": [],
    }


def _pending_analysis(reason: str = "pending") -> dict[str, Any]:
    return {"status": reason}


def _public(article: dict[str, Any]) -> dict[str, Any]:
    out = {k: article.get(k) for k in PUBLIC_FIELDS}
    out["companies"] = out["companies"] or []
    out["topics"] = out["topics"] or []
    out["also_covered_by"] = out["also_covered_by"] or []
    return out


def _sort_key(article: dict[str, Any]) -> float:
    dt = parse_iso(article.get("published_at"))
    return dt.timestamp() if dt else 0.0


def run(config: dict[str, Any], news_path: Path = NEWS_PATH, health_path: Path = SOURCE_HEALTH_PATH,
        use_ai: bool = True, check_urls: bool | None = None, dry_run: bool = False,
        now: datetime | None = None, session=None) -> dict[str, Any]:
    now = now or utc_now()
    settings = config["settings"]
    started = iso(now)
    errors: list[str] = []

    db = read_json(news_path, None) or empty_database(config)
    db.setdefault("meta", empty_database(config)["meta"])
    archive: list[dict[str, Any]] = db.get("articles", [])
    known_urls = {canonical_url(a["url"]) for a in archive}
    known_urls |= {canonical_url(c["url"]) for a in archive for c in a.get("also_covered_by", []) if c.get("url")}

    # 1. Fetch
    session = session or http_session(config)
    results = fetch_all(config, now=now, session=session)
    for r in results:
        if not r.ok:
            errors.append(f"source:{r.source_id}: {r.error}")
    health = source_health_report(results)
    content_by_id = {item["id"]: item.get("content", "") for r in results for item in r.items}

    # 2-4. Freshness, relevance, classification
    candidates = []
    stale = irrelevant = 0
    per_source_cap = settings.get("max_items_per_source", 6)
    for r in results:
        kept_from_source = 0
        for item in sorted(r.items, key=lambda i: i["published_at"], reverse=True):
            if kept_from_source >= per_source_cap:
                break
            if canonical_url(item["url"]) in known_urls:
                continue
            if not within_freshness(item, settings.get("freshness_days", 3), now):
                stale += 1
                continue
            if classify(item, config, now) is None:
                irrelevant += 1
                continue
            cat_terms = matched_terms(item["title"] + " " + item.get("content", ""), config["categories"][item["category"]]["keywords"])
            item["topics"] = cat_terms[:4]
            item["companies"] = []
            candidates.append(item)
            kept_from_source += 1
    candidates.sort(key=lambda a: (PRIORITY_WEIGHT[a["priority"]], a["priority_score"], _sort_key(a)), reverse=True)
    candidates = candidates[: settings.get("max_new_articles_per_run", 60)]

    # Dedupe candidates among themselves first so we don't validate duplicates.
    candidates, dup_new = deduplicate(candidates, settings.get("duplicate_title_similarity", 0.6), settings.get("duplicate_window_hours", 72))

    # 5. URL validation
    if check_urls is None:
        check_urls = settings.get("validate_article_urls", True)
    if check_urls and candidates:
        with ThreadPoolExecutor(max_workers=settings.get("max_workers", 8)) as pool:
            checks = list(pool.map(lambda a: validate_article_url(a["url"], session, settings.get("request_timeout_seconds", 20)), candidates))
        kept = []
        for art, status in zip(candidates, checks):
            if status == "invalid":
                errors.append(f"url_invalid:{art['source_id']}: {art['url']}")
                continue
            art["url_check"] = status
            kept.append(art)
        invalid_urls = len(candidates) - len(kept)
        candidates = kept
    else:
        invalid_urls = 0
        for art in candidates:
            art["url_check"] = "not_checked"

    for art in candidates:
        art["analysis"] = _pending_analysis()
        art["ai_attempts"] = 0

    # 6. Deduplicate against archive (archive first so existing records win ties)
    merged, dup_archive = deduplicate(archive + candidates, settings.get("duplicate_title_similarity", 0.6), settings.get("duplicate_window_hours", 72))
    merged_ids = {a["id"] for a in merged}
    new_articles = [a for a in candidates if a["id"] in merged_ids]

    # 7. AI analysis
    ai_done = ai_failed = 0
    provider = analyse_news.resolve_provider(config)
    ai_rate_limited = False
    max_attempts = config["ai"].get("max_ai_attempts", settings.get("max_ai_attempts", 3))
    queue = [a for a in merged if (a.get("analysis") or {}).get("status") in ("pending", "failed", "skipped_no_key")
             and a.get("ai_attempts", 0) < max_attempts]
    # Spend the (free) quota on stories with real feed text first; headline-only items last.
    queue.sort(key=lambda a: (bool(content_by_id.get(a["id"]) or a.get("excerpt")),
                              PRIORITY_WEIGHT.get(a.get("priority"), 1), _sort_key(a)), reverse=True)
    queue = queue[: settings.get("max_ai_articles_per_run", 30)]
    if not use_ai:
        LOG.info("AI analysis disabled for this run (--no-ai)")
    elif not provider:
        LOG.warning("No AI provider available (add a free GEMINI_API_KEY secret, or OPENAI_API_KEY): "
                    "articles saved with rule-based classification and publisher excerpts only")
        for a in queue:
            a["analysis"] = _pending_analysis("skipped_no_key")
        if queue:
            errors.append("ai: no AI provider configured (add the free GEMINI_API_KEY secret); analysis skipped")
    else:
        LOG.info("AI provider: %s (model %s), %d article(s) queued", provider["name"], provider["model"], len(queue))
        gap = float(provider.get("seconds_between_calls", 0) or 0)
        max_consecutive = settings.get("max_consecutive_ai_failures", 3)
        consecutive = 0
        for i, a in enumerate(queue):
            if consecutive >= max_consecutive:
                errors.append(f"ai: stopped after {consecutive} consecutive failures; remaining articles stay queued")
                LOG.error("Stopping AI after %d consecutive failures. Remaining articles stay queued.", consecutive)
                break
            if i and gap:
                time.sleep(gap)  # stay inside free-tier requests-per-minute limits
            a["content"] = content_by_id.get(a["id"]) or a.get("content") or a.get("excerpt") or ""
            try:
                analysis = analyse_news.analyse_article(a, config, provider=provider)
                analyse_news.apply_analysis(a, analysis, config)
                ai_done += 1
                consecutive = 0
            except analyse_news.RateLimited as exc:
                ai_rate_limited = True
                errors.append(f"ai: {provider['name']} quota reached; remaining articles wait for the next run ({str(exc)[:120]})")
                LOG.warning("Rate limit reached on %s. Remaining articles stay queued for the next run.", provider["name"])
                break
            except PermissionError as exc:
                errors.append(f"ai: {exc}")
                LOG.error("%s Stopping AI processing for this run.", exc)
                break
            except Exception as exc:
                ai_failed += 1
                consecutive += 1
                a["ai_attempts"] = a.get("ai_attempts", 0) + 1
                a["analysis"] = {"status": "failed", "error": f"{type(exc).__name__}: {str(exc)[:200]}"}
                errors.append(f"ai:{a['id']}: {type(exc).__name__}: {str(exc)[:200]}")
                LOG.warning("AI analysis failed for %s: %s", a["id"], exc)
                continue
            a["ai_attempts"] = a.get("ai_attempts", 0) + 1

    # 8. Archive limit (newest publication dates kept)
    merged.sort(key=_sort_key, reverse=True)
    limit = settings.get("archive_limit", 100)
    trimmed = max(0, len(merged) - limit)
    merged = merged[:limit]

    sources_ok = sum(1 for r in results if r.ok)
    status = "success" if sources_ok and not errors else "partial" if sources_ok else "failed"
    finished = iso(utc_now())
    meta = db["meta"]
    meta.update({
        "schema_version": SCHEMA_VERSION,
        "generated_at": finished,
        "archive_limit": limit,
        "schedule_utc": config.get("schedule_utc", []),
        "repository": os.getenv("GITHUB_REPOSITORY") or meta.get("repository"),
        "categories": {k: v["label"] for k, v in config["categories"].items()},
        "ai_enabled": bool(provider) and use_ai,
        "ai_provider": provider["name"] if provider and use_ai else None,
        "ai_model": provider["model"] if provider and use_ai else None,
        "last_run": {
            "started_at": started,
            "finished_at": finished,
            "status": status,
            "trigger": os.getenv("GITHUB_EVENT_NAME", "manual"),
            "sources_total": len(results),
            "sources_ok": sources_ok,
            "sources_failed": len(results) - sources_ok,
            "new_articles": len(new_articles),
            "skipped_stale": stale,
            "skipped_irrelevant": irrelevant,
            "invalid_urls": invalid_urls,
            "duplicates_merged": dup_new + dup_archive,
            "ai_processed": ai_done,
            "ai_failed": ai_failed,
            "ai_rate_limited": ai_rate_limited,
            "archived_out": trimmed,
            "errors": errors[:50],
        },
    })
    if sources_ok:
        meta["last_successful_update"] = finished
    db["articles"] = [_public(a) for a in merged]

    LOG.info("Run %s: %d/%d sources ok, %d new, %d AI analysed, %d AI failed, %d in archive",
             status, sources_ok, len(results), len(new_articles), ai_done, ai_failed, len(merged))
    if not dry_run:
        write_json(news_path, db)
        write_json(health_path, health)
    return db


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the Signal news pipeline")
    parser.add_argument("--no-ai", action="store_true")
    parser.add_argument("--no-url-check", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    setup_logging()
    config = load_config()
    try:
        db = run(config, use_ai=not args.no_ai, check_urls=False if args.no_url_check else None, dry_run=args.dry_run)
    except Exception:
        LOG.exception("Pipeline crashed; existing data/news.json left untouched")
        return 1
    return 2 if db["meta"]["last_run"]["status"] == "failed" else 0


if __name__ == "__main__":
    sys.exit(main())
