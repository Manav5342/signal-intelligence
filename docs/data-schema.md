# `data/news.json` schema (v1)

The pipeline writes one JSON file that the static dashboard reads. It's structured so it can later
move to a database (each article is a self-contained record with a stable `id`).

The example below is a **structural sample only**: the values are placeholders, not real news.

```json
{
  "meta": {
    "schema_version": 1,
    "project": "Signal",
    "generated_at": "2026-01-01T00:35:12Z",
    "last_successful_update": "2026-01-01T00:35:12Z",
    "archive_limit": 100,
    "schedule_utc": ["30 0 * * *", "30 8 * * *"],
    "repository": "your-username/signal-intelligence",
    "categories": { "ai": "AI & Technology", "b2b": "B2B Marketing", "email": "Email Marketing",
                    "whatsapp": "WhatsApp Marketing", "analytics": "Marketing Analytics", "martech": "Marketing Technology" },
    "ai_enabled": true,
    "last_run": {
      "started_at": "2026-01-01T00:31:02Z",
      "finished_at": "2026-01-01T00:35:12Z",
      "status": "success | partial | failed",
      "trigger": "schedule | workflow_dispatch | manual",
      "sources_total": 33, "sources_ok": 31, "sources_failed": 2,
      "new_articles": 12, "skipped_stale": 140, "skipped_irrelevant": 210,
      "invalid_urls": 0, "duplicates_merged": 3,
      "ai_processed": 12, "ai_failed": 0, "archived_out": 4,
      "errors": ["source:example-id: HTTPError: 404 ..."]
    }
  },
  "articles": [
    {
      "id": "16-char hash of the canonical URL",
      "title": "Original headline exactly as published",
      "url": "https://publisher.example/original-article",
      "canonical_url": "https://publisher.example/original-article",
      "source": "Publisher name (original attribution)",
      "source_id": "config source id",
      "via": "Google News: … (only for aggregator sources, else null)",
      "credibility": "official | publication | aggregator",
      "published_at": "Original publication date from the feed (UTC)",
      "collected_at": "When Signal collected it (UTC)",
      "category": "ai | b2b | email | whatsapp | analytics | martech",
      "category_label": "Email Marketing",
      "region": "Global | India",
      "region_reason": "Why the region was assigned",
      "priority": "High | Medium | Low",
      "priority_score": 12,
      "excerpt": "Up to ~300 characters of the publisher's own feed text",
      "companies": ["Companies named in the text"],
      "topics": ["short", "tags"],
      "also_covered_by": [{ "source": "Other publisher", "url": "https://…", "title": "…" }],
      "url_check": "valid | restricted | not_checked",
      "classification": "ai | rules",
      "ai_attempts": 1,
      "analysis": {
        "status": "complete | pending | failed | skipped_no_key",
        "model": "model id that produced it",
        "generated_at": "…",
        "evidence": "feed_full_text | feed_excerpt | headline_only",
        "reported_facts": "Facts stated by the publisher only",
        "summary": "Detailed plain-language summary",
        "why_it_matters": "Business implications",
        "applications": ["Practical marketing applications"],
        "recommendations": ["Strategic recommendations"],
        "priority_reason": "…",
        "needs_validation": false,
        "validation_note": ""
      }
    }
  ]
}
```

`data/source_health.json` holds the per-feed result of the last run (`ok`, `status_code`, `entries`, `error`).
