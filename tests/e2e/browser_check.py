"""Optional end-to-end browser check (not run in CI).

    pip install playwright && python -m playwright install chromium
    python tests/e2e/browser_check.py [--chrome /usr/bin/google-chrome] [--shots out_dir]

Copies the site to a temp folder with a PLACEHOLDER news.json (clearly fake test data that is
never published), serves it locally, and exercises search, filters, sorting, the article modal,
saved articles (including persistence across reload), empty/error states and mobile layout.
"""
import argparse
import functools
import http.server
import json
import shutil
import socketserver
import sys
import tempfile
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
CATS = {"ai": "AI & Technology", "b2b": "B2B Marketing", "email": "Email Marketing",
        "whatsapp": "WhatsApp Marketing", "analytics": "Marketing Analytics", "martech": "Marketing Technology"}


def placeholder_db(n=14):
    now = datetime.now(timezone.utc)
    arts = []
    keys = list(CATS)
    for i in range(n):
        cat = keys[i % len(keys)]
        done = i % 3 != 2
        arts.append({
            "id": f"test{i:02d}", "title": f"[Placeholder {i}] Test headline about {CATS[cat].lower()} for layout checks",
            "url": f"https://example.com/placeholder/{i}", "canonical_url": f"https://example.com/placeholder/{i}",
            "source": ["Example Publisher", "Sample Daily", "Test Wire"][i % 3], "source_id": "test", "via": None,
            "credibility": "publication", "published_at": (now - timedelta(hours=5 * i)).isoformat().replace("+00:00", "Z"),
            "collected_at": now.isoformat(), "category": cat, "category_label": CATS[cat],
            "region": "India" if i % 4 == 1 else "Global", "region_reason": "Placeholder.",
            "priority": ["High", "Medium", "Low"][i % 3], "priority_score": 14 - i,
            "excerpt": "Placeholder excerpt text used only to test the layout. Not real news.",
            "companies": ["ExampleCo"] if i == 0 else [], "topics": ["placeholder"], "url_check": "valid",
            "also_covered_by": [{"source": "Other Example", "url": "https://example.org/x", "title": "Placeholder"}] if i == 0 else [],
            "classification": "ai" if done else "rules", "ai_attempts": 1,
            "analysis": ({"status": "complete", "model": "test", "generated_at": now.isoformat(), "evidence": "feed_excerpt",
                          "reported_facts": "Placeholder facts.", "summary": "Placeholder AI summary for layout testing only.",
                          "why_it_matters": "Placeholder reasoning.", "applications": ["Placeholder application one", "Placeholder application two"],
                          "recommendations": ["Placeholder recommendation"], "priority_reason": "Placeholder.",
                          "needs_validation": i == 0, "validation_note": "Placeholder validation note." if i == 0 else ""}
                         if done else {"status": "skipped_no_key"}),
        })
    return {"meta": {"schema_version": 1, "last_successful_update": now.isoformat(), "generated_at": now.isoformat(),
                     "schedule_utc": ["30 0 * * *", "30 8 * * *"], "repository": "example/signal-intelligence",
                     "categories": CATS, "ai_enabled": True,
                     "last_run": {"status": "partial", "sources_total": 30, "sources_ok": 28, "sources_failed": 2}},
            "articles": arts}


def serve(directory):
    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *a):
            pass
    handler = functools.partial(Quiet, directory=str(directory))
    httpd = socketserver.TCPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--chrome", default=None)
    ap.add_argument("--shots", default=None)
    args = ap.parse_args()
    tmp = Path(tempfile.mkdtemp())
    for item in ("index.html", "assets"):
        src = ROOT / item
        shutil.copytree(src, tmp / item) if src.is_dir() else shutil.copy(src, tmp / item)
    (tmp / "data").mkdir()
    (tmp / "data" / "news.json").write_text(json.dumps(placeholder_db()))
    (tmp / "data" / "source_health.json").write_text(json.dumps({"checked_at": datetime.now(timezone.utc).isoformat(), "total": 30, "ok": 28, "failed": 2,
                                                              "sources": [{"name": "Broken Example", "ok": False}, {"name": "Down Example", "ok": False}]}))
    httpd = serve(tmp)
    base = f"http://127.0.0.1:{httpd.server_address[1]}/"
    shots = Path(args.shots) if args.shots else None
    if shots:
        shots.mkdir(parents=True, exist_ok=True)
    failures = []

    def check(cond, msg):
        print(("PASS " if cond else "FAIL ") + msg)
        if not cond:
            failures.append(msg)

    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=args.chrome) if args.chrome else p.chromium.launch()
        ctx = browser.new_context(viewport={"width": 1366, "height": 900})
        page = ctx.new_page()
        console_errors = []
        page.on("console", lambda m: console_errors.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: console_errors.append(str(e)))
        page.goto(base)
        page.wait_for_selector("#latest-list .story[data-id]")
        page.evaluate("document.fonts.ready")
        check(page.evaluate("document.fonts.check('700 40px \"Source Serif\"') && document.fonts.check('40px \"Signal Nameplate\"')"), "self-hosted fonts load")
        check(page.inner_text("#m-total") == "14", "metric: total articles")
        check(page.inner_text("#m-high") == "5", "metric: high priority count")
        check("IST" in page.inner_text("#m-next"), "metric: next update shown in IST")
        check(page.locator("#lead-story article").count() == 1, "lead story rendered")
        check(page.locator("#top-list .rail-story").count() >= 1, "top developments rail rendered")
        check(page.locator("#desk-grid .desk").count() == 6, "six section desks rendered")
        check("edition" in page.inner_text("#edition-name").lower(), "edition name in masthead")
        check(not page.is_hidden("#notice"), "partial-run notice shown")
        check(page.evaluate("document.querySelector('.signature').naturalWidth > 0"), "signature image loads")
        check(page.get_attribute(".signoff-link", "href") == "https://meetmanav.com", "signature link points to meetmanav.com")
        if shots:
            page.screenshot(path=str(shots / "desktop.png"), full_page=True)
            page.screenshot(path=str(shots / "desktop-fold.png"))

        def latest(sel):
            return page.locator("#latest-list " + sel).all_inner_texts()

        page.fill("#search", "Placeholder 3]")
        page.wait_for_timeout(350)
        check(page.locator("#latest-list .story").count() == 1, "search by headline")
        check(page.is_hidden("#top-section") and page.is_hidden("#desks-section"), "front page hides while searching")
        page.fill("#search", "exampleco")
        page.wait_for_timeout(350)
        check(page.locator("#latest-list .story").count() == 1, "search by company")
        page.fill("#search", "sample daily")
        page.wait_for_timeout(350)
        check(page.locator("#latest-list .story").count() == 5, "search by publisher")
        page.fill("#search", "zzzz-nothing")
        page.wait_for_timeout(350)
        check(page.locator("#latest-list .empty").count() == 1, "no-results empty state")
        page.click("#clear-filters")

        page.click('#section-nav a[href="#/category/email"]')
        page.wait_for_timeout(150)
        check(latest(".kicker span:nth-child(1)") and all(t == "Email Marketing" for t in latest(".kicker span:nth-child(1)")), "category section filter")
        check(page.inner_text("#latest-title") == "Email Marketing", "section page title")
        check(page.get_attribute('#section-nav a[href="#/category/email"]', "aria-current") == "page", "active section in nav")
        page.click('#section-nav a[href="#/region/India"]')
        page.wait_for_timeout(150)
        check(latest(".kicker span:nth-child(3)") and all(t == "India" for t in latest(".kicker span:nth-child(3)")), "India section filter")
        page.click('#section-nav a[href="#/"]')
        page.click('#region-seg [data-region="Global"]')
        check(all(t == "Global" for t in latest(".kicker span:nth-child(3)")), "region toggle")
        page.click("#clear-filters")
        page.select_option("#f-priority", "High")
        check(all(t == "High priority" for t in latest(".kicker span:nth-child(5)")), "priority filter")
        page.select_option("#f-priority", "all")
        page.select_option("#f-source", "Test Wire")
        check(all(t == "Test Wire" for t in latest(".byline .pub")), "source filter")
        page.click("#clear-filters")
        page.select_option("#f-date", "today")
        check(page.locator("#latest-list .story").count() >= 1, "date filter (today)")
        page.click("#clear-filters")
        page.select_option("#f-sort", "oldest")
        check("[Placeholder 13]" in page.locator("#latest-list .story .hl").first.inner_text(), "sort oldest first")
        page.select_option("#f-sort", "priority")
        check(page.locator("#latest-list .story").first.get_attribute("class").find("is-high") >= 0, "sort high priority first")
        page.select_option("#f-sort", "newest")

        page.locator('#latest-list [data-action="open"][data-id="test00"]').first.click()
        page.wait_for_selector("#article-modal[open]")
        body = page.inner_text("#modal-body")
        for label in ("What Example Publisher reported", "Why this matters", "Practical marketing applications", "Strategic recommendations", "Read the original", "Check before acting", "Also covered by", "Signal analysis"):
            check(label.lower() in body.lower(), f"reader contains '{label}'")
        check(page.get_attribute("#modal-body .reader-actions a.btn-ink", "href") == "https://example.com/placeholder/0", "reader source link")
        page.wait_for_timeout(400)
        if shots:
            page.screenshot(path=str(shots / "reader.png"))
            page.locator("#article-modal .reader").evaluate("el => el.scrollTop = 520")
            page.screenshot(path=str(shots / "reader-2.png"))
        page.keyboard.press("Escape")
        check(not page.locator("#article-modal[open]").count(), "reader closes with Escape")

        page.locator('#latest-list [data-action="save"][data-id="test01"]').click()
        check(page.inner_text("#saved-count") == "1", "saving increments saved count")
        page.reload()
        page.wait_for_selector("#latest-list .story[data-id]")
        check(page.inner_text("#saved-count") == "1", "saved persists across reload")
        page.click('#section-nav a[href="#/saved"]')
        page.wait_for_timeout(200)
        check(page.locator("#latest-list .story").count() == 1 and page.is_hidden("#metrics") and page.inner_text("#latest-title") == "Saved articles", "saved view lists bookmark")
        page.click('#section-nav a[href="#/"]')

        page.click("#refresh-btn")
        check(page.get_attribute("#run-workflow-link", "href") == "https://github.com/example/signal-intelligence/actions/workflows/refresh-news.yml", "run-collection link points to workflow")
        page.click("#reload-data-btn")
        page.wait_for_timeout(500)
        check(page.is_visible("#toast"), "reload data shows toast")

        page.wait_for_selector("#desk-grid .desk")
        page.locator('#desk-grid a[href="#/category/ai"]').click()
        page.wait_for_timeout(150)
        check(all(t == "AI & Technology" for t in latest(".kicker span:nth-child(1)")), "desk link opens section")

        # Mobile
        m = browser.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=2, is_mobile=True, has_touch=True)
        mp = m.new_page()
        mp.on("pageerror", lambda e: console_errors.append(str(e)))
        mp.goto(base)
        mp.wait_for_selector("#latest-list .story[data-id]")
        overflow = mp.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")
        check(overflow <= 0, f"mobile: no horizontal overflow ({overflow}px)")
        if shots:
            mp.screenshot(path=str(shots / "mobile.png"), full_page=False)
            mp.screenshot(path=str(shots / "mobile-full.png"), full_page=True)
            mp.locator('[data-action="open"]').first.click()
            mp.wait_for_selector("#article-modal[open]")
            mp.wait_for_timeout(400)
            mp.screenshot(path=str(shots / "mobile-reader.png"))
        m.close()

        # Empty database and failed load
        (tmp / "data" / "news.json").write_text(json.dumps({"meta": {"last_successful_update": None}, "articles": []}))
        e = browser.new_page()
        e.goto(base)
        e.wait_for_selector("#latest-list .empty")
        check("first edition" in e.inner_text("#latest-list"), "empty database state")
        if shots:
            e.screenshot(path=str(shots / "empty.png"))
        (tmp / "data" / "news.json").unlink()
        e.reload()
        e.wait_for_selector("#latest-list .empty")
        check("didn’t arrive" in e.inner_text("#latest-list"), "missing data error state")
        check(not console_errors, f"no JS errors / CSP violations ({console_errors[:3]})")
        browser.close()
    httpd.shutdown()
    print(f"\n{len(failures)} failure(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
