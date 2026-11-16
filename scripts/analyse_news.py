"""AI analysis via the OpenAI Chat Completions API.

The model only sees what the publisher syndicated in its feed (headline, date, publisher,
summary/content). It is instructed to separate reported facts from interpretation, never
invent numbers or capabilities, and flag when the source text is too thin.
"""
from __future__ import annotations

import json
import logging
import os
import time
from typing import Any

import requests

from .classify import PRIORITIES, REGIONS
from .common import iso, utc_now

LOG = logging.getLogger("signal.ai")
OPENAI_URL = "https://api.openai.com/v1/chat/completions"


class AIUnavailable(Exception):
    """Raised when no API key is configured."""


SYSTEM_PROMPT = """You are Signal, an analyst writing for a B2B marketing professional who works on marketing operations, lead generation, CRM, email campaigns, WhatsApp automation and marketing analytics (in India and globally).

You will receive ONE article as syndicated by its publisher (headline, publisher, date, and the feed text, which may be only a short excerpt).

Rules:
- "reported_facts" must contain ONLY what the provided text states. Attribute to the publisher ("<Publisher> reports..."). No outside knowledge, no invented numbers, dates, prices, features or quotes.
- Everything else (why_it_matters, applications, recommendations) is your interpretation. Keep it specific to THIS article. No generic advice that would fit any article.
- If the provided text is too short to know details (e.g. only a headline), say so plainly in reported_facts, keep interpretation cautious, and set needs_validation to true with a note on what to verify in the original article.
- Never claim a product can do something unless the text says so.
- Region: "India" only if the development's geographic relevance is India (Indian market, users, regulation, pricing, or launch). A story that merely mentions an Indian company is "Global".
- Priority: "High" = likely to change how a B2B marketer works soon (platform/policy/pricing change, major launch, deadline). "Medium" = useful development worth tracking. "Low" = background or minor.
- Plain, professional British English. No hype, no emojis.

Return ONLY a JSON object with exactly these keys:
{
  "reported_facts": "2-4 sentences, facts from the text only",
  "summary": "A detailed 3-5 sentence plain-language explanation of the development (facts first, clearly marked interpretation if any)",
  "why_it_matters": "2-4 sentences on business implications for B2B marketing, acquisition, campaign performance, automation or sales-marketing alignment",
  "applications": ["3-4 concrete ways a B2B marketer could apply this"],
  "recommendations": ["3-4 actionable items: what to explore/test, relevant tool types, likely benefit, implementation considerations"],
  "category": one of CATEGORY_KEYS,
  "region": "Global" or "India",
  "region_reason": "one sentence",
  "priority": "High" | "Medium" | "Low",
  "priority_reason": "one sentence",
  "companies": ["companies named in the text"],
  "topics": ["2-5 short topic tags"],
  "needs_validation": true or false,
  "validation_note": "what to verify in the original source, or empty string"
}"""


def build_messages(article: dict[str, Any], config: dict[str, Any]) -> list[dict[str, str]]:
    cats = ", ".join(f'"{k}" ({v["label"]})' for k, v in config["categories"].items())
    text = article.get("content") or ""
    evidence = "feed_full_text" if len(text) > 1500 else "feed_excerpt" if text else "headline_only"
    user = {
        "headline": article["title"],
        "publisher": article["source"],
        "published_at_utc": article["published_at"],
        "url": article["url"],
        "rule_based_category_guess": article.get("category"),
        "feed_text_type": evidence,
        "feed_text": text[:5000] or "(No body text was syndicated in the feed. Only the headline is available.)",
    }
    return [
        {"role": "system", "content": SYSTEM_PROMPT.replace("CATEGORY_KEYS", cats)},
        {"role": "user", "content": json.dumps(user, ensure_ascii=False)},
    ]


def _str(value: Any, limit: int = 1500) -> str:
    return str(value).strip()[:limit] if isinstance(value, (str, int, float)) else ""


def _list(value: Any, limit: int = 5, item_limit: int = 400) -> list[str]:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return []
    return [s for s in (_str(v, item_limit) for v in value) if s][:limit]


def parse_ai_response(content: str, config: dict[str, Any]) -> dict[str, Any]:
    """Validate and normalise the model's JSON. Raises ValueError if unusable."""
    text = (content or "").strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text[text.find("{"):]
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("No JSON object in AI response")
    data = json.loads(text[start:end + 1])
    if not isinstance(data, dict):
        raise ValueError("AI response is not a JSON object")

    out = {
        "reported_facts": _str(data.get("reported_facts")),
        "summary": _str(data.get("summary"), 2500),
        "why_it_matters": _str(data.get("why_it_matters"), 2000),
        "applications": _list(data.get("applications")),
        "recommendations": _list(data.get("recommendations")),
        "region_reason": _str(data.get("region_reason"), 300),
        "priority_reason": _str(data.get("priority_reason"), 300),
        "companies": _list(data.get("companies"), 8, 80),
        "topics": _list(data.get("topics"), 6, 40),
        "needs_validation": bool(data.get("needs_validation")),
        "validation_note": _str(data.get("validation_note"), 500),
    }
    if not out["summary"] or not out["why_it_matters"]:
        raise ValueError("AI response missing summary or why_it_matters")
    category = _str(data.get("category")).lower()
    out["category"] = category if category in config["categories"] else None
    region = _str(data.get("region")).title()
    out["region"] = region if region in REGIONS else None
    priority = _str(data.get("priority")).title()
    out["priority"] = priority if priority in PRIORITIES else None
    return out


def call_openai(messages: list[dict[str, str]], config: dict[str, Any], api_key: str, session: requests.Session | None = None) -> tuple[str, str]:
    """Return (content, model_used). Tries the configured model, then fallbacks on 404/400 model errors."""
    session = session or requests.Session()
    ai = config["ai"]
    models = [os.getenv("OPENAI_MODEL") or ai["model"]] + [m for m in ai.get("fallback_models", []) if m]
    last_error = None
    for model in dict.fromkeys(models):
        payload = {
            "model": model,
            "messages": messages,
            "response_format": {"type": "json_object"},
            "max_completion_tokens": ai.get("max_output_tokens", 1400),
        }
        for attempt in range(ai.get("max_retries", 3)):
            try:
                resp = session.post(
                    OPENAI_URL,
                    headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                    json=payload,
                    timeout=ai.get("request_timeout_seconds", 90),
                )
            except requests.RequestException as exc:
                last_error = f"network error: {exc}"
                time.sleep(2 ** attempt)
                continue
            if resp.status_code == 200:
                body = resp.json()
                return body["choices"][0]["message"]["content"], body.get("model", model)
            snippet = resp.text[:300]
            last_error = f"HTTP {resp.status_code}: {snippet}"
            if resp.status_code in (429, 500, 502, 503, 504):
                time.sleep(min(30, 2 ** (attempt + 1)))
                continue
            if resp.status_code == 401:
                raise PermissionError("OpenAI rejected the API key (401). Check the OPENAI_API_KEY secret.")
            break  # 400/404 etc: try next model
        LOG.warning("Model %s failed: %s", model, last_error)
    raise RuntimeError(last_error or "OpenAI request failed")


def analyse_article(article: dict[str, Any], config: dict[str, Any], api_key: str | None = None, session: requests.Session | None = None) -> dict[str, Any]:
    api_key = api_key if api_key is not None else os.getenv("OPENAI_API_KEY", "")
    if not api_key.strip():
        raise AIUnavailable("OPENAI_API_KEY is not set")
    content, model = call_openai(build_messages(article, config), config, api_key.strip(), session)
    parsed = parse_ai_response(content, config)
    text = article.get("content") or ""
    parsed.update({
        "status": "complete",
        "model": model,
        "generated_at": iso(utc_now()),
        "evidence": "feed_full_text" if len(text) > 1500 else "feed_excerpt" if text else "headline_only",
    })
    if parsed["evidence"] == "headline_only":
        parsed["needs_validation"] = True
        parsed["validation_note"] = parsed["validation_note"] or "Only the headline was available to the AI. Read the original article before acting."
    return parsed


def apply_analysis(article: dict[str, Any], analysis: dict[str, Any], config: dict[str, Any]) -> None:
    """Merge validated AI fields onto the article (AI may refine category/region/priority)."""
    if analysis.get("category"):
        article["category"] = analysis["category"]
        article["category_label"] = config["categories"][analysis["category"]]["label"]
    if analysis.get("region"):
        article["region"] = analysis["region"]
        article["region_reason"] = analysis.get("region_reason") or article.get("region_reason")
    if analysis.get("priority"):
        article["priority"] = analysis["priority"]
    if analysis.get("companies"):
        article["companies"] = analysis["companies"]
    if analysis.get("topics"):
        article["topics"] = analysis["topics"]
    article["classification"] = "ai"
    keep = ("status", "model", "generated_at", "evidence", "reported_facts", "summary", "why_it_matters",
            "applications", "recommendations", "priority_reason", "needs_validation", "validation_note")
    article["analysis"] = {k: analysis.get(k) for k in keep}
