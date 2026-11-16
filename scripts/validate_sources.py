"""Source and URL validation.

`python -m scripts.validate_sources` checks every configured feed and writes
data/source_health.json. `validate_article_url` is used by the pipeline before an
article is saved.

URL outcomes:
  valid       2xx/3xx response
  restricted  401/403/405/429/5xx: the server exists but blocks automated checks or is busy;
              kept, and flagged in the data
  invalid     404/410, DNS failure, connection failure, unsafe URL; not saved
"""
from __future__ import annotations

import argparse
import logging
import sys
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import requests

from .common import (SOURCE_HEALTH_PATH, http_session, iso, is_safe_public_url, load_config,
                     setup_logging, utc_now, write_json)
from .fetch_news import fetch_source

LOG = logging.getLogger("signal.validate")
RESTRICTED = {401, 403, 405, 406, 429, 500, 502, 503, 504}


def validate_article_url(url: str, session: requests.Session, timeout: float = 15) -> str:
    if not is_safe_public_url(url):
        return "invalid"
    try:
        resp = session.head(url, allow_redirects=True, timeout=timeout)
        if resp.status_code in (405, 403, 400) or resp.status_code >= 500:
            resp = session.get(url, allow_redirects=True, timeout=timeout, stream=True)
            resp.close()
        code = resp.status_code
    except requests.RequestException as exc:
        LOG.debug("URL check failed for %s: %s", url, exc)
        return "invalid"
    if code < 400:
        return "valid" if is_safe_public_url(resp.url) else "invalid"
    if code in RESTRICTED:
        return "restricted"
    return "invalid"


def source_health_report(results: list[Any]) -> dict[str, Any]:
    return {
        "checked_at": iso(utc_now()),
        "total": len(results),
        "ok": sum(1 for r in results if r.ok),
        "failed": sum(1 for r in results if not r.ok),
        "sources": [
            {
                "id": r.source_id, "name": r.name, "url": r.url, "ok": r.ok,
                "status_code": r.status_code, "entries": r.entries_seen,
                "usable_items": len(r.items), "error": r.error,
            }
            for r in results
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check every configured feed.")
    parser.add_argument("--no-write", action="store_true", help="Print results only")
    args = parser.parse_args(argv)
    setup_logging()
    config = load_config()
    session = http_session(config)
    sources = [s for s in config["sources"] if s.get("enabled", True)]
    timeout = config["settings"].get("request_timeout_seconds", 20)
    with ThreadPoolExecutor(max_workers=config["settings"].get("max_workers", 8)) as pool:
        results = list(pool.map(lambda s: fetch_source(s, session, timeout), sources))
    report = source_health_report(results)
    for s in report["sources"]:
        mark = "OK  " if s["ok"] else "FAIL"
        print(f"{mark} {s['id']:<28} entries={s['entries']:<4} {s['error'] or ''}")
    print(f"\n{report['ok']}/{report['total']} sources healthy")
    if not args.no_write:
        write_json(SOURCE_HEALTH_PATH, report)
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
