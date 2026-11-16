"""Send one small request to the configured AI provider and print exactly what comes back.

  python -m scripts.check_ai

Used by the "Validate sources" workflow to diagnose AI setup problems quickly.
"""
from __future__ import annotations

import sys

import requests

from .analyse_news import parse_ai_response, resolve_provider
from .common import load_config, setup_logging


def main() -> int:
    setup_logging()
    config = load_config()
    provider = resolve_provider(config)
    if not provider:
        print("No AI provider available: set GITHUB_TOKEN (with models: read), GEMINI_API_KEY or OPENAI_API_KEY.")
        return 1
    print(f"Provider: {provider['name']}  model: {provider['model']}  url: {provider['url']}")
    headers = {"Authorization": f"Bearer {provider['key']}", "Content-Type": "application/json"}
    headers.update(provider.get("extra_headers") or {})
    payload = {
        "model": provider["model"],
        "messages": [
            {"role": "system", "content": "Reply with a JSON object only."},
            {"role": "user", "content": 'Return {"summary": "ok", "why_it_matters": "ok", "category": "ai", "priority": "Low", "region": "Global"}'},
        ],
        "response_format": {"type": "json_object"},
        provider.get("token_param", "max_tokens"): 100,
    }
    try:
        resp = requests.post(provider["url"], headers=headers, json=payload, timeout=60, allow_redirects=False)
    except requests.RequestException as exc:
        print(f"Network error: {exc}")
        return 1
    print(f"HTTP {resp.status_code}  content-type: {resp.headers.get('content-type')}")
    for h in ("x-ratelimit-remaining-requests", "x-ratelimit-limit-requests", "retry-after", "location"):
        if resp.headers.get(h):
            print(f"{h}: {resp.headers[h]}")
    print("Body (first 600 chars):")
    print(resp.text[:600])
    if resp.status_code != 200:
        return 1
    try:
        content = resp.json()["choices"][0]["message"]["content"]
        parse_ai_response(content, config)
    except Exception as exc:
        print(f"\nResponse could not be used: {type(exc).__name__}: {exc}")
        return 1
    print("\nAI provider works.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
