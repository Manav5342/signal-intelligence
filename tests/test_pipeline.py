"""Tests for RSS parsing, deduplication, classification, AI parsing and the pipeline.
All network calls are mocked; fixture content is placeholder text on example.com."""
import json

import pytest
import requests

from conftest import make_article
from scripts import analyse_news, run_pipeline
from scripts.classify import classify, detect_region
from scripts.deduplicate import canonical_url, deduplicate, normalise_title, title_similarity
from scripts.fetch_news import SourceResult, fetch_source, feed_url, parse_feed, within_freshness
from scripts.validate_sources import validate_article_url

SRC = {"id": "test", "name": "Test Feed", "type": "rss", "url": "https://example.com/feed",
       "category_hint": "email", "region_hint": "Global", "credibility": "publication", "focused": False}


# ---------- RSS parsing ----------
def test_parse_feed_extracts_dated_safe_items(feed_bytes, now):
    items, seen = parse_feed(feed_bytes, SRC, now)
    assert seen == 5
    titles = [i["title"] for i in items]
    assert "Test: Undated item should be skipped" not in titles  # never invent dates
    assert all(i["url"].startswith("https://") for i in items)  # javascript: link dropped
    assert len(items) == 3
    first = items[0]
    assert first["published_at"] == "2026-11-16T03:00:00Z"
    assert "<p>" not in first["excerpt"] and "email deliverability" in first["excerpt"]
    assert first["source"] == "Test Feed"


def test_google_news_feed_uses_original_publisher(now):
    xml = b"""<?xml version="1.0"?><rss version="2.0"><channel><title>GN</title>
    <item><title>Placeholder headline about WhatsApp Business - Example Times</title>
    <link>https://news.google.com/rss/articles/abc</link><pubDate>Mon, 16 Nov 2026 02:00:00 GMT</pubDate>
    <source url="https://example.org">Example Times</source><description>x</description></item></channel></rss>"""
    src = dict(SRC, type="google_news", query="x", name="Google News: X")
    items, _ = parse_feed(xml, src, now)
    assert items[0]["source"] == "Example Times"
    assert items[0]["via"] == "Google News: X"
    assert items[0]["title"] == "Placeholder headline about WhatsApp Business"
    assert "news.google.com/rss/search?q=" in feed_url(src)


def test_failed_source_does_not_raise():
    class Boom:
        def get(self, *a, **k):
            raise requests.ConnectionError("DNS failure")
    res = fetch_source(SRC, Boom(), 5)
    assert res.ok is False and "ConnectionError" in res.error


def test_freshness_window(now):
    assert within_freshness({"published_at": "2026-11-14T06:00:00Z"}, 3, now)
    assert not within_freshness({"published_at": "2026-11-01T06:00:00Z"}, 3, now)


# ---------- Deduplication ----------
def test_canonical_url_strips_tracking():
    a = canonical_url("https://www.Example.com/post/?utm_source=x&id=2&fbclid=abc#top")
    assert a == "https://example.com/post?id=2"


def test_normalise_title():
    assert normalise_title("OpenAI Launches  New Agent!  - TechSite", strip_publisher=True) == "openai launches new agent"


def test_duplicate_url_and_title_removed():
    a = make_article(id="1", url="https://example.com/a?utm_source=rss", title="Alpha beta gamma delta launch")
    b = make_article(id="2", url="https://example.com/a", title="Different title entirely here now")
    c = make_article(id="3", url="https://example.com/c", title="Alpha beta gamma delta launch")
    unique, removed = deduplicate([a, b, c])
    assert removed == 2 and len(unique) == 1


def test_similar_story_from_other_publisher_merged():
    a = make_article(id="1", url="https://one.example.com/x", source="One",
                     title="Meta raises WhatsApp Business template message prices across India markets")
    b = make_article(id="2", url="https://two.example.com/y", source="Two",
                     title="Meta raises WhatsApp Business template message prices in India markets")
    unique, removed = deduplicate([a, b])
    assert removed == 1 and len(unique) == 1
    assert unique[0]["also_covered_by"][0]["source"] == "Two"


def test_different_articles_on_same_topic_kept():
    a = make_article(id="1", url="https://one.example.com/x", source="One",
                     title="OpenAI launches new agent builder for enterprise sales teams")
    b = make_article(id="2", url="https://two.example.com/y", source="Two",
                     title="OpenAI changes API pricing for reasoning models and batch jobs")
    unique, removed = deduplicate([a, b])
    assert removed == 0 and len(unique) == 2
    assert title_similarity(a["title"], b["title"]) < 0.6


def test_similar_titles_far_apart_in_time_kept():
    a = make_article(id="1", url="https://one.example.com/x", source="One", published_at="2026-11-01T00:00:00Z",
                     title="Google updates Gmail bulk sender requirements for marketing email senders")
    b = make_article(id="2", url="https://two.example.com/y", source="Two", published_at="2026-11-15T00:00:00Z",
                     title="Google updates Gmail bulk sender requirements for marketing email senders again")
    unique, _ = deduplicate([a, b])
    assert len(unique) == 2


# ---------- Classification ----------
def test_category_classification(config, now):
    email = make_article(title="Gmail tightens DMARC rules for bulk sender email deliverability",
                         content="SPF DKIM DMARC sender reputation")
    wa = make_article(title="WhatsApp Business Platform adds new template message categories",
                      content="Click-to-WhatsApp ads and broadcasts")
    ai = make_article(title="Anthropic releases new Claude model for enterprise AI agents",
                      content="agentic AI generative AI")
    assert classify(email, config, now)["category"] == "email"
    assert classify(wa, config, now)["category"] == "whatsapp"
    assert classify(ai, config, now)["category"] == "ai"


def test_irrelevant_article_dropped(config, now):
    art = make_article(title="City council approves new park", content="Trees and benches for residents.")
    assert classify(art, config, now) is None


def test_region_requires_geographic_relevance(config):
    mention_only = make_article(title="Freshworks reports quarterly results for global CRM business",
                                content="The company, founded in Chennai, sells CRM software worldwide.",
                                region_hint="India")
    region, reason = detect_region(mention_only, config)
    assert region == "Global"
    india = make_article(title="WhatsApp pricing changes for businesses in India")
    assert detect_region(india, config)[0] == "India"
    body = make_article(title="New pricing for template messages",
                        content="Businesses in India will pay in rupees; TRAI guidance also applies.")
    assert detect_region(body, config)[0] == "India"


# ---------- AI response parsing ----------
GOOD = {
    "reported_facts": "Example reports X.", "summary": "S", "why_it_matters": "W",
    "applications": ["a1", "a2"], "recommendations": ["r1"], "category": "email",
    "region": "global", "region_reason": "r", "priority": "high", "priority_reason": "p",
    "companies": ["Example"], "topics": ["dmarc"], "needs_validation": False, "validation_note": "",
}


def test_parse_ai_response_valid(config):
    out = analyse_news.parse_ai_response(json.dumps(GOOD), config)
    assert out["priority"] == "High" and out["region"] == "Global" and out["category"] == "email"


def test_parse_ai_response_fenced_and_invalid_enums(config):
    bad = dict(GOOD, category="sports", priority="urgent", region="Mars")
    out = analyse_news.parse_ai_response("```json\n" + json.dumps(bad) + "\n```", config)
    assert out["category"] is None and out["priority"] is None and out["region"] is None


def test_parse_ai_response_rejects_incomplete(config):
    with pytest.raises(ValueError):
        analyse_news.parse_ai_response(json.dumps({"summary": ""}), config)
    with pytest.raises(ValueError):
        analyse_news.parse_ai_response("not json at all", config)


def test_missing_api_key_raises(config):
    assert analyse_news.resolve_provider(config) is None
    with pytest.raises(analyse_news.AIUnavailable):
        analyse_news.analyse_article(make_article(title="t"), config)


def test_resolve_provider_uses_free_gemini_by_default(config):
    assert analyse_news.resolve_provider(config, {}) is None
    assert analyse_news.resolve_provider(config, {"GITHUB_TOKEN": "ghs_x"}) is None  # GitHub Models retired
    p = analyse_news.resolve_provider(config, {"GEMINI_API_KEY": "g"})
    assert p["name"] == "gemini" and p["model"] == "gemini-2.5-flash-lite"
    assert p["url"] == "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
    p = analyse_news.resolve_provider(config, {"GEMINI_API_KEY": "g", "OPENAI_API_KEY": "sk"})
    assert p["name"] == "openai"
    p = analyse_news.resolve_provider(config, {"GEMINI_API_KEY": "g", "OPENAI_API_KEY": "sk", "AI_PROVIDER": "gemini", "AI_MODEL": "gemini-2.5-flash"})
    assert p["name"] == "gemini" and p["model"] == "gemini-2.5-flash"
    assert analyse_news.resolve_provider(config, {"AI_PROVIDER": "openai", "GEMINI_API_KEY": "g"}) is None


def gh_provider(config):
    return analyse_news.resolve_provider(config, {"GEMINI_API_KEY": "test-key"})


class FakeResp:
    def __init__(self, status, body, headers=None):
        self.status_code, self._body, self.text = status, body, json.dumps(body)
        self.headers = headers or {}

    def json(self):
        return self._body


class FakeAISession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls, self.payloads, self.urls = [], [], []

    def post(self, url, **kw):
        self.calls.append(kw["json"]["model"])
        self.payloads.append(dict(kw["json"]))
        self.urls.append(url)
        return self.responses.pop(0)


def _session(responses):
    return FakeAISession(responses)


OK = FakeResp(200, {"model": "m", "choices": [{"message": {"content": json.dumps(GOOD)}}]})


def test_call_model_falls_back_on_model_error(config):
    ok = FakeResp(200, {"model": "gemini-flash-lite-latest", "choices": [{"message": {"content": json.dumps(GOOD)}}]})
    sess = _session([FakeResp(404, {"error": "unknown model"}), ok])
    content, model = analyse_news.call_model([], gh_provider(config), config, sess)
    assert model == "gemini-flash-lite-latest" and sess.calls == ["gemini-2.5-flash-lite", "gemini-flash-lite-latest"]
    assert sess.urls[0] == "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
    assert sess.payloads[0]["max_tokens"] == 3000 and "max_completion_tokens" not in sess.payloads[0]


def test_call_model_drops_json_mode_if_unsupported(config):
    sess = _session([FakeResp(400, {"error": "response_format not supported"}), OK])
    analyse_news.call_model([], gh_provider(config), config, sess)
    assert "response_format" in sess.payloads[0] and "response_format" not in sess.payloads[1]


def test_call_model_daily_quota_raises_rate_limited(config):
    sess = _session([FakeResp(429, {"error": "quota"}, {"retry-after": "40000"})])
    with pytest.raises(analyse_news.RateLimited):
        analyse_news.call_model([], gh_provider(config), config, sess)


def test_call_model_bad_credentials(config):
    with pytest.raises(PermissionError):
        analyse_news.call_model([], gh_provider(config), config, _session([FakeResp(401, {"error": "bad"})]))


def test_headline_only_forces_validation(config):
    out = analyse_news.analyse_article(make_article(title="t", content=""), config, gh_provider(config), _session([OK]))
    assert out["evidence"] == "headline_only" and out["needs_validation"] is True and out["provider"] == "gemini"


# ---------- URL validation ----------
class FakeHTTP:
    def __init__(self, code, final="https://example.com/a"):
        self.code, self.final = code, final

    def _r(self):
        r = type("R", (), {})()
        r.status_code, r.url, r.close = self.code, self.final, lambda: None
        return r

    def head(self, *a, **k):
        return self._r()

    def get(self, *a, **k):
        return self._r()


def test_validate_article_url():
    assert validate_article_url("https://example.com/a", FakeHTTP(200)) == "valid"
    assert validate_article_url("https://example.com/a", FakeHTTP(404)) == "invalid"
    assert validate_article_url("https://example.com/a", FakeHTTP(403)) == "restricted"
    assert validate_article_url("http://127.0.0.1/x", FakeHTTP(200)) == "invalid"
    assert validate_article_url("ftp://example.com/x", FakeHTTP(200)) == "invalid"


# ---------- End-to-end pipeline (mocked network) ----------
def _fake_fetch(feed_bytes, fail=False):
    def inner(config, now=None, session=None):
        ok_items, _ = parse_feed(feed_bytes, SRC, now)
        results = [SourceResult("test", "Test Feed", SRC["url"], True, ok_items, None, 5, 200)]
        results.append(SourceResult("broken", "Broken", "https://broken.example", False, [], "HTTPError: 500", 0, 500))
        if fail:
            results = [results[1]]
        return results
    return inner


def test_pipeline_empty_db_no_key(tmp_path, config, feed_bytes, now, monkeypatch):
    monkeypatch.setattr(run_pipeline, "fetch_all", _fake_fetch(feed_bytes))
    news, health = tmp_path / "news.json", tmp_path / "health.json"
    db = run_pipeline.run(config, news, health, check_urls=False, now=now)
    titles = [a["title"] for a in db["articles"]]
    assert len(titles) == 2 and not any("bakery" in t for t in titles)
    assert all(a["analysis"]["status"] == "skipped_no_key" for a in db["articles"])
    assert all("content" not in a for a in db["articles"])  # full feed text not republished
    run_meta = db["meta"]["last_run"]
    assert run_meta["sources_failed"] == 1 and run_meta["status"] == "partial"
    assert db["meta"]["last_successful_update"]
    assert json.loads(health.read_text())["failed"] == 1
    wa = next(a for a in db["articles"] if "WhatsApp" in a["title"])
    assert wa["region"] == "India" and wa["category"] == "whatsapp"


def test_pipeline_preserves_archive_and_limits(tmp_path, config, feed_bytes, now, monkeypatch):
    monkeypatch.setattr(run_pipeline, "fetch_all", _fake_fetch(feed_bytes))
    news, health = tmp_path / "news.json", tmp_path / "health.json"
    old = run_pipeline.empty_database(config)
    old["articles"] = [dict(make_article(id=f"old{i}", url=f"https://example.com/old{i}", title=f"Old story number {i} placeholder",
                                         published_at=f"2026-10-{10+i:02d}T00:00:00Z"), analysis={"status": "complete", "summary": "s"})
                       for i in range(5)]
    news.write_text(json.dumps(old))
    cfg = json.loads(json.dumps(config))
    cfg["settings"]["archive_limit"] = 4
    db = run_pipeline.run(cfg, news, health, check_urls=False, now=now)
    ids = [a["id"] for a in db["articles"]]
    assert len(ids) == 4 and "old4" in ids and "old3" in ids  # newest kept, old preserved
    # Second run: nothing new, nothing deleted
    db2 = run_pipeline.run(cfg, news, health, check_urls=False, now=now)
    assert [a["id"] for a in db2["articles"]] == ids and db2["meta"]["last_run"]["new_articles"] == 0


def test_pipeline_all_sources_failed(tmp_path, config, feed_bytes, now, monkeypatch):
    monkeypatch.setattr(run_pipeline, "fetch_all", _fake_fetch(feed_bytes, fail=True))
    db = run_pipeline.run(config, tmp_path / "n.json", tmp_path / "h.json", check_urls=False, now=now)
    assert db["meta"]["last_run"]["status"] == "failed" and db["meta"]["last_successful_update"] is None


def test_pipeline_with_ai(tmp_path, config, feed_bytes, now, monkeypatch):
    monkeypatch.setattr(run_pipeline, "fetch_all", _fake_fetch(feed_bytes))
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    calls = []

    def fake_analyse(article, config, provider=None, session=None):
        calls.append(article["id"])
        if "DMARC" in article["title"]:
            raise ValueError("bad json")
        out = analyse_news.parse_ai_response(json.dumps(dict(GOOD, category="whatsapp", region="India")), config)
        out.update(status="complete", model="test", generated_at="2026-11-16T06:00:00Z", evidence="feed_excerpt")
        return out

    monkeypatch.setattr(analyse_news, "analyse_article", fake_analyse)
    db = run_pipeline.run(config, tmp_path / "n.json", tmp_path / "h.json", check_urls=False, now=now)
    statuses = {a["title"][:20]: a["analysis"]["status"] for a in db["articles"]}
    assert sorted(statuses.values()) == ["complete", "failed"]
    assert db["meta"]["last_run"]["ai_processed"] == 1 and db["meta"]["last_run"]["ai_failed"] == 1
    assert db["meta"]["ai_provider"] == "openai"


def test_pipeline_free_tier_rate_limit_keeps_articles_queued(tmp_path, config, feed_bytes, now, monkeypatch):
    monkeypatch.setattr(run_pipeline, "fetch_all", _fake_fetch(feed_bytes))
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(run_pipeline.time, "sleep", lambda s: None)
    seen = []

    def fake_analyse(article, config, provider=None, session=None):
        seen.append(provider["name"])
        raise analyse_news.RateLimited("HTTP 429")

    monkeypatch.setattr(analyse_news, "analyse_article", fake_analyse)
    db = run_pipeline.run(config, tmp_path / "n.json", tmp_path / "h.json", check_urls=False, now=now)
    assert seen == ["gemini"]  # stopped after the first 429
    assert all(a["analysis"]["status"] == "pending" and a["ai_attempts"] == 0 for a in db["articles"])
    assert db["meta"]["last_run"]["ai_rate_limited"] is True and db["meta"]["ai_provider"] == "gemini"


class TextResp(FakeResp):
    def __init__(self, status, text, headers=None):
        super().__init__(status, {}, headers)
        self.text = text

    def json(self):
        raise ValueError("Expecting value: line 1 column 1 (char 0)")


def test_non_json_200_gives_a_clear_error(config):
    sess = _session([TextResp(200, "<html>Sign in</html>", {"content-type": "text/html"})])
    with pytest.raises(RuntimeError, match="non-JSON response: HTTP 200, content-type text/html"):
        analyse_news.call_model([], gh_provider(config), config, sess)


def test_provider_request_does_not_follow_redirects(config):
    class Capture(FakeAISession):
        def post(self, url, **kw):
            self.headers = kw["headers"]
            self.redirects = kw.get("allow_redirects")
            return super().post(url, **kw)
    sess = Capture([OK])
    analyse_news.call_model([], gh_provider(config), config, sess)
    assert sess.headers["Authorization"] == "Bearer test-key" and sess.redirects is False


def test_pipeline_stops_after_consecutive_ai_failures(tmp_path, config, feed_bytes, now, monkeypatch):
    monkeypatch.setattr(run_pipeline, "fetch_all", _fake_fetch(feed_bytes))
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(run_pipeline.time, "sleep", lambda s: None)
    cfg = json.loads(json.dumps(config))
    cfg["settings"]["max_consecutive_ai_failures"] = 1
    calls = []

    def boom(article, config, provider=None, session=None):
        calls.append(article["id"])
        raise RuntimeError("broken")

    monkeypatch.setattr(analyse_news, "analyse_article", boom)
    db = run_pipeline.run(cfg, tmp_path / "n.json", tmp_path / "h.json", check_urls=False, now=now)
    assert len(calls) == 1
    statuses = sorted(a["analysis"]["status"] for a in db["articles"])
    assert statuses == ["failed", "pending"]
