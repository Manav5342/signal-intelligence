# Signal: B2B Marketing & AI Intelligence Dashboard

**Your Daily Intelligence Brief.** *Make sense of what’s moving business forward.*

Signal is a personal intelligence portal. Twice a day it collects the latest developments in AI, B2B marketing, email, WhatsApp marketing, marketing analytics and martech from official blogs, industry publications and Indian outlets. It removes duplicates, categorises each article, labels it Global or India, and adds AI analysis: a summary, why it matters, practical applications and strategic recommendations. Everything is published as a fast static dashboard on GitHub Pages.

- **Runs without your laptop.** GitHub Actions collects news at **6:00 AM and 2:00 PM IST** (00:30 and 08:30 UTC).
- **Completely free.** GitHub Pages and GitHub Actions are free for public repositories, and AI analysis uses the free tier of the Google Gemini API: a free key, no credit card (see [Costs](#costs)).
- **No secrets in the browser.** Any AI credentials live only in GitHub Actions. The website is plain HTML, CSS and JS that reads `data/news.json`.

## The design: a twice-daily business paper
Signal is laid out like a printed business daily:
- **Masthead** with a blackletter nameplate, the edition (Morning edition for the 6 AM run, Afternoon edition for the 2 PM run) and the dateline.
- **Section bar**: Front page, one section per category, India, and Saved.
- **Front page**: the lead story (the highest-priority development of the last 48 hours) with its standfirst and *Why it matters*, plus a rail of the next top developments.
- **Latest Intelligence** in ruled newspaper columns. High-priority stories get larger headlines.
- **From the desks**: the leading stories in each section.
- **Article reader**: opens like a printed article. It shows *What the publisher reported* in its own box, kept separate from the *Signal analysis* written by AI.

Typography: UnifrakturMaguntia (nameplate), Source Serif 4 (headlines and body) and Libre Franklin (labels). All three are self-hosted in `assets/fonts/` under the SIL Open Font License, so the page makes no third-party requests.

Quick customisations:
- **Paper colour:** in `assets/css/styles.css`, change `--paper` (salmon newsprint by default, the colour of business dailies) to `#fdfcf9` for white newsprint. Also adjust `--paper-deep` and `--paper-light`.
- **Dateline city:** in `assets/js/app.js`, change `DATELINE_CITY`.
- **Stories per page:** `PAGE_SIZE` in `assets/js/app.js`.

---

## How it works

```
GitHub Actions (cron 00:30 + 08:30 UTC, or "Run workflow")
  └─ python -m scripts.run_pipeline
       1. fetch_news.py       RSS/Atom feeds from config.json (one failure never stops the run)
       2. freshness filter    only items published in the last N days (settings.freshness_days)
       3. classify.py         relevance, category, region (India only with real geographic relevance), priority
       4. validate_sources.py checks each new article URL resolves before saving
       5. deduplicate.py      canonical URL + normalised headline + same story from other publishers
       6. analyse_news.py     AI analysis via Gemini (free tier) or OpenAI (paid) (facts vs interpretation, validated JSON)
       7. archive             merge with existing articles, keep newest `archive_limit` (default 100)
       8. writes data/news.json + data/source_health.json, commits them, deploys to GitHub Pages
Browser
  └─ index.html + assets/js/app.js  read data/news.json (no API keys, no tokens)
```

## Project structure

```
signal-intelligence/
├── index.html                    Dashboard
├── assets/
│   ├── css/styles.css            Newspaper styles (responsive, print-friendly)
│   ├── js/lib.js                 Pure logic: filters, search, sorting, schedule, metrics
│   ├── js/app.js                 UI: front page, sections, reader, saved articles, refresh controls
│   ├── fonts/                    Self-hosted OFL fonts + LICENSE.txt
│   └── images/                   Favicon
├── data/
│   ├── news.json                 The news database (starts empty, never filled with dummy news)
│   └── source_health.json        Per-feed status from the last run
├── scripts/
│   ├── run_pipeline.py           Orchestrates a full run
│   ├── fetch_news.py             Feed fetching and parsing
│   ├── classify.py               Relevance, category, region, priority rules
│   ├── deduplicate.py            Duplicate detection
│   ├── analyse_news.py           AI analysis (Gemini free tier or OpenAI) and response validation
│   ├── validate_sources.py       Feed health and article-URL checks
│   └── common.py                 Shared helpers
├── tests/                        pytest suite, Node tests for lib.js, optional browser check
├── docs/data-schema.md           JSON structure, with a placeholder sample
├── .github/workflows/
│   ├── refresh-news.yml          Scheduled collection and Pages deployment
│   ├── validate-sources.yml      Checks every feed (manual, plus weekly)
│   └── ci.yml                    Tests and a frontend secret scan on every push
├── config.json                   Sources, categories, keywords, archive limit, AI model
├── requirements.txt              feedparser, requests
└── requirements-dev.txt          + pytest, PyYAML
```

---

## Deploy it: step by step

All you need is a free GitHub account and a free Google account (for the Gemini API key). No credit card is required.

### 1. Create the repository
1. On GitHub, click **+ → New repository**.
2. Name it `signal-intelligence`, set it to **Public**, and don’t add a README. Click **Create repository**.
   GitHub Pages is free on public repositories. Private repositories need a paid GitHub plan for Pages.

### 2. Upload the project
The upload must include the hidden `.github` folder and the `.nojekyll` file. The most reliable way is the command line (or GitHub Desktop):

```bash
cd signal-intelligence            # the unzipped folder
git init -b main
git add .
git commit -m "Initial Signal setup"
git remote add origin https://github.com/YOUR-USERNAME/signal-intelligence.git
git push -u origin main
```

> If you drag and drop files in the GitHub web UI, check that `.github/workflows/refresh-news.yml` shows up in the repo. macOS hides dot-folders in Finder; press `Cmd + Shift + .` to show them.

### 3. Turn on GitHub Pages
**Settings → Pages → Build and deployment → Source: GitHub Actions.**

### 4. Allow the workflow to save data
**Settings → Actions → General → Workflow permissions → Read and write permissions → Save.**
This lets the scheduled run commit the updated `data/news.json`, which is how the archive is preserved between runs.

### 5. Add a free Gemini API key (for AI analysis)
1. Go to https://aistudio.google.com/apikey and sign in with any Google account.
2. Click **Create API key**. No credit card or billing is needed for the free tier.
3. In your GitHub repo, open **Settings → Secrets and variables → Actions → New repository secret**.
4. Name it `GEMINI_API_KEY`, paste the key, and click **Add secret**.

Signal picks the provider automatically:
| Secret present | Provider used | Cost |
|---|---|---|
| `OPENAI_API_KEY` | OpenAI API | Paid (pay as you go) |
| `GEMINI_API_KEY` only | Google Gemini API, free tier (`gemini-3.5-flash-lite`) | Free. Google's pricing page notes that free-tier requests may be used to improve Google products. |
| neither | No AI. Stories show publisher excerpts and rule-based sections. | Free |

To force a provider or model, add repository **variables** `AI_PROVIDER` (`gemini` or `openai`) and/or `AI_MODEL`. To test the AI setup on its own, run **Actions → Validate sources**. Its summary includes an AI provider check.

> GitHub Models, which GitHub offered as a free AI service, was retired by GitHub on 30 July 2026, so Signal doesn't use it.

### 6. Run the first collection manually
1. Open the **Actions** tab. If asked, click **I understand my workflows, go ahead and enable them**.
2. Optional but recommended: select **Validate sources → Run workflow**. The run summary shows which feeds respond from GitHub’s servers (see [Sources](#sources)).
3. Select **Refresh news → Run workflow → Run workflow**.
4. Wait about 3–6 minutes. The run summary shows sources OK/failed, new articles, AI processed and errors.

### 7. Open your dashboard
`https://YOUR-USERNAME.github.io/signal-intelligence/`
The address is also shown under **Settings → Pages** and in the deploy job of the workflow run.

That’s it. From now on it updates at 6:00 AM and 2:00 PM IST automatically.

---

## Manual refresh: what each control does
The **Refresh** button in the top bar has two clearly separated options:

| Option | What it does |
|---|---|
| **Reload data** | Re-downloads the already-published `data/news.json`. Instant. No new collection, no AI calls. |
| **Run a new collection** | Opens the `Refresh news` workflow on GitHub. You click **Run workflow** there while signed in. The dashboard then checks every minute (up to 15 minutes) and loads new data when the run finishes. |

**Why not a one-click button that runs the workflow from the page?** Starting a GitHub Actions run requires an authenticated GitHub token. GitHub Pages is static hosting with no server, so any token placed in the page would be readable by every visitor and could be abused. Signal therefore sends you to GitHub, where your own login authorises the run. Only people with write access to your repo can start it. If you later want a true one-click button, the secure pattern is a tiny serverless function (for example a Cloudflare Worker) that holds a fine-grained token server-side and is protected by your own login. That needs a separate backend, so it isn’t included.

You can also trigger runs from a terminal with the GitHub CLI: `gh workflow run refresh-news.yml`.

---

## Testing the scheduled automation
- Scheduled runs appear in **Actions → Refresh news** with the event **schedule**. Check after 06:00 or 14:00 IST.
- GitHub can start scheduled runs **a few minutes to occasionally longer than that** after the cron time when its runners are busy. This is normal.
- Schedules only run from the **default branch** (`main`).
- To test sooner, temporarily add a near-term cron to `refresh-news.yml` (e.g. `- cron: '*/15 * * * *'` for every 15 minutes), push, watch one run succeed, then remove it.
- In public repositories, GitHub may disable scheduled workflows after 60 days without repository activity. If that happens, a banner appears in the Actions tab. Click **Enable workflow**.
- The dashboard’s **Last update** card turns grey if no successful update has happened in 20 hours. That’s a quick sign that a schedule was missed.

## Running locally (optional)
```bash
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
python -m scripts.validate_sources --no-write           # check feeds from your machine
python -m scripts.run_pipeline --no-ai                  # collect without OpenAI
GEMINI_API_KEY=... python -m scripts.run_pipeline      # full run with free Gemini
python -m http.server 8000                              # open http://localhost:8000
```
Open the dashboard through a local server. Opening `index.html` directly from disk blocks `fetch()` and the page shows a clear error.

Tests:
```bash
python -m pytest -q tests                  # pipeline: parsing, dedup, classification, AI parsing, archive
node --test tests/frontend/lib.test.js     # dashboard logic: search, filters, sorting, schedule
python tests/e2e/browser_check.py          # optional: real browser (needs Playwright), uses placeholder data only
```

---

## Configuration (`config.json`)
| Setting | Default | Meaning |
|---|---|---|
| `settings.archive_limit` | 100 | Articles kept. Older ones (by publication date) roll off. |
| `settings.freshness_days` | 3 | Only items published within this window are added. Existing archive items are kept. |
| `settings.max_new_articles_per_run` | 60 | Cap on new articles per run (highest priority first). |
| `settings.max_ai_articles_per_run` | 30 | Cap on OpenAI calls per run. This is your cost ceiling. |
| `settings.min_relevance_score` | 3 | Keyword threshold for general (non-focused) sources. |
| `settings.duplicate_title_similarity` | 0.6 | Headline similarity for cross-publisher duplicates. Higher = stricter. |
| `settings.duplicate_window_hours` | 72 | Same-story matching only within this time window. |
| `settings.validate_article_urls` | true | Check article links before saving. |
| `ai.provider` | `auto` | `auto` picks OpenAI if its key exists, otherwise Gemini. Override with the `AI_PROVIDER` variable. |
| `ai.providers.*.model` | `gemini-3.5-flash-lite` | Per-provider model and fallbacks. Override with the `AI_MODEL` variable. |
| `ai.providers.*.seconds_between_calls` | 7 (Gemini) | Pause between AI calls to stay inside per-minute limits. |
| `categories.*.keywords` | — | Edit to tune what counts as each category. |
| `india_terms` | — | Geographic signals for the India label. Company names are deliberately excluded. |
| `sources[]` | 33 feeds | Add, remove or set `"enabled": false`. |

**Adding a source:** add an object to `sources` with `id`, `name`, `type: "rss"`, `url`, `category_hint`, `region_hint`, `credibility` (`official`/`publication`/`aggregator`) and `focused` (true if the feed is entirely on-topic). Then run **Validate sources**.

To change the schedule, edit both crons in `refresh-news.yml` **and** `schedule_utc` in `config.json` (the dashboard uses the latter for “Next update”).

## Sources
The starting list covers OpenAI, Google AI, Microsoft AI, MIT Technology Review, TechCrunch, HubSpot, Demand Gen Report, Marketing Brew, Search Engine Journal/Land, MarTech, Litmus, Mailgun, Validity, Email on Acid, Google Workspace Updates, Meta Newsroom, Wati, Salesforce, Google Analytics, Power BI, Inc42, YourStory, MediaNama and ET Tech. It also includes Google News topic feeds for gaps where no official RSS exists: Anthropic, WhatsApp Business (global and India), email deliverability, B2B marketing, HubSpot, exchange4media and Indian SaaS/martech.

**Honest notes**
- Feed URLs were written from publicly documented feed locations but **couldn’t be fetched from the environment this project was built in**. Run **Validate sources** once after deploying. Any feed that has moved shows as FAIL, and the dashboard footer lists unavailable sources. Fix the URL or set `"enabled": false`. A failing feed never stops the run.
- Google News items link through `news.google.com` redirects to the original article. The publisher name shown is the original publisher from the feed’s `<source>` element.
- Some RSS feeds include only a headline or a short excerpt. The AI sees only what the feed provides; Signal never scrapes article pages. When the text is thin, the analysis is marked **Further validation required**.
- Only short excerpts (~300 characters) are stored publicly in `news.json`. Full feed text is used for analysis during the run but not republished.

## AI analysis quality safeguards
- The prompt separates **Reported by [publisher]** (facts from the feed text only) from **Signal analysis** (AI interpretation). The dashboard labels them visually.
- The model is told never to invent numbers, dates, quotes or product capabilities, and to set `needs_validation` when the source text is insufficient. Headline-only items are always flagged.
- Responses must be valid JSON with required fields. Category, region and priority must be from the allowed values or they’re ignored in favour of the rule-based result. Failed analyses retry on later runs (up to 3 attempts).
- India is assigned only for real geographic relevance (Indian market, users, pricing, regulators, cities), never just because an Indian company is named.

## Costs
| Item | Cost |
|---|---|
| GitHub Pages hosting | Free (public repo) |
| GitHub Actions | Free for public repos. Each run takes a few minutes. |
| Feeds | Free (public RSS) |
| AI analysis (Gemini API free tier) | Free, rate-limited |

**Free-tier limits and how Signal stays inside them.** Google limits free-tier requests per minute and per day per project, and has changed these limits several times. Signal is built to cope:
- it analyses at most `max_ai_articles_per_run` (20) stories per run, so at most 40 requests a day;
- it waits `seconds_between_calls` (7 s) between requests to stay under per-minute limits;
- if the quota runs out, it stops cleanly. Unanalysed stories stay queued for the next run, and the dashboard says so;
- it tries fallback models (`gemini-flash-lite-latest`, `gemini-3.5-flash`, …) if Google retires the default.

Paid AI is optional: if you add `OPENAI_API_KEY`, Signal uses OpenAI instead. Check current prices at https://openai.com/api/pricing and set a spending limit.

## Security
- `GEMINI_API_KEY` / `OPENAI_API_KEY` exist only as GitHub Actions secrets and in the runner’s environment during a run. They are never written to any file.
- The frontend contains no keys or tokens. `ci.yml` scans `index.html` and `assets/` for key-like strings on every push.
- A Content-Security-Policy restricts the page to its own scripts, styles and data. All feed text is HTML-escaped before display, and only `http(s)` links are rendered.
- Article URLs are checked to be public `http(s)` addresses (no localhost/private IPs) before saving.
- The deployed site contains only `index.html`, `assets/` and `data/`. Scripts and tests are not published.

## What was tested before delivery
- Python suite (24 tests, all network mocked): RSS parsing (undated and unsafe links skipped), Google News attribution, failed-source isolation, freshness, URL canonicalisation, duplicate URL/headline/cross-publisher detection, keeping genuinely different stories, category classification, India-vs-Global logic, AI JSON parsing and validation, model fallback, missing API key, URL validation, empty database, archive preservation and limit, all-sources-failed, and mixed AI success/failure.
- Frontend logic (Node, 11 tests): escaping, safe URLs, IST “today”, next 06:00/14:00 IST run, search by headline/company/topic/publisher, every filter, all three sort orders, top developments, metrics, repo detection.
- Real-browser check (Chrome, placeholder data): self-hosted fonts load, lead story, top-developments rail and six section desks render, edition name, metrics, search (headline/company/publisher), section, India, region, date, priority and source filters, all three sorts, article reader sections and source link, saving persists across reload, saved view, refresh controls, empty and error states, no JS errors or CSP violations, and a 390px mobile layout with no horizontal overflow.
- `actionlint` on all three workflows.
- **Not tested:** live feeds and real OpenAI calls (the build environment had no access to them), and the actual scheduled GitHub Actions runs. Those happen once you deploy. Follow steps 6 and [Testing the scheduled automation](#testing-the-scheduled-automation) to confirm them.
