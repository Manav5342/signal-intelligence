import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.common import load_config  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures"
NOW = datetime(2026, 11, 16, 6, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def clean_ai_env(monkeypatch):
    for k in ("GITHUB_TOKEN", "GEMINI_API_KEY", "OPENAI_API_KEY", "AI_PROVIDER", "AI_MODEL"):
        monkeypatch.delenv(k, raising=False)


@pytest.fixture
def config():
    return load_config()


@pytest.fixture
def now():
    return NOW


@pytest.fixture
def feed_bytes():
    return (FIXTURES / "sample_feed.xml").read_bytes()


def make_article(**kw):
    base = {
        "id": kw.get("id", "x"),
        "title": "Test headline",
        "url": "https://example.com/a",
        "source": "Example",
        "source_id": "example",
        "credibility": "publication",
        "published_at": "2026-11-16T03:00:00Z",
        "content": "",
        "excerpt": "",
        "category_hint": None,
        "region_hint": "Global",
        "focused_source": False,
        "feed_tags": [],
    }
    base.update(kw)
    return base
