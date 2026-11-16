// node --test tests/frontend/
const test = require("node:test");
const assert = require("node:assert");
const L = require("../../assets/js/lib.js");

const NOW = new Date("2026-11-16T06:00:00Z"); // 11:30 IST
const A = [
  { id: "1", title: "Gmail updates DMARC rules", source: "Example A", category: "email", region: "Global", priority: "High", priority_score: 14, published_at: "2026-11-16T02:00:00Z", companies: ["Google"], topics: ["dmarc"] },
  { id: "2", title: "WhatsApp pricing in India", source: "Example B", category: "whatsapp", region: "India", priority: "Medium", priority_score: 8, published_at: "2026-11-15T10:00:00Z", analysis: { status: "complete", summary: "Template pricing changes for Indian businesses." } },
  { id: "3", title: "Old AI story", source: "Example A", category: "ai", region: "Global", priority: "Low", priority_score: 2, published_at: "2026-10-01T00:00:00Z" },
];

test("escapeHtml neutralises markup", () => {
  assert.strictEqual(L.escapeHtml('<img src=x onerror="a">'), "&lt;img src=x onerror=&quot;a&quot;&gt;");
});

test("safeUrl only allows http(s)", () => {
  assert.strictEqual(L.safeUrl("javascript:alert(1)"), null);
  assert.strictEqual(L.safeUrl("data:text/html,x"), null);
  assert.ok(L.safeUrl("https://example.com/a").startsWith("https://"));
});

test("next scheduled run is 06:00 or 14:00 IST", () => {
  assert.strictEqual(L.nextScheduledRun(new Date("2026-11-16T06:00:00Z")).toISOString(), "2026-11-16T08:30:00.000Z");
  assert.strictEqual(L.nextScheduledRun(new Date("2026-11-16T09:00:00Z")).toISOString(), "2026-11-17T00:30:00.000Z");
  assert.strictEqual(L.nextScheduledRun(new Date("2026-11-16T00:10:00Z")).toISOString(), "2026-11-16T00:30:00.000Z");
});

test("today is computed in IST", () => {
  // 2026-11-15T20:00Z is 01:30 IST on the 16th
  assert.ok(L.isTodayIST("2026-11-15T20:00:00Z", NOW));
  assert.ok(!L.isTodayIST("2026-11-15T10:00:00Z", NOW));
});

test("filters: category, region, priority, source, date, search", () => {
  assert.deepStrictEqual(L.filterArticles(A, { category: "email" }, NOW).map(a => a.id), ["1"]);
  assert.deepStrictEqual(L.filterArticles(A, { region: "India" }, NOW).map(a => a.id), ["2"]);
  assert.deepStrictEqual(L.filterArticles(A, { priority: "Low" }, NOW).map(a => a.id), ["3"]);
  assert.deepStrictEqual(L.filterArticles(A, { source: "Example A" }, NOW).map(a => a.id), ["1", "3"]);
  assert.deepStrictEqual(L.filterArticles(A, { date: "7" }, NOW).map(a => a.id), ["1", "2"]);
  assert.deepStrictEqual(L.filterArticles(A, { date: "today" }, NOW).map(a => a.id), ["1"]);
  assert.deepStrictEqual(L.filterArticles(A, { query: "google" }, NOW).map(a => a.id), ["1"]);   // company
  assert.deepStrictEqual(L.filterArticles(A, { query: "template indian" }, NOW).map(a => a.id), ["2"]); // summary, multi-term
  assert.deepStrictEqual(L.filterArticles(A, { query: "example b" }, NOW).map(a => a.id), ["2"]); // publisher
  assert.strictEqual(L.filterArticles(A, { query: "nonexistent" }, NOW).length, 0);
});

test("sorting", () => {
  assert.deepStrictEqual(L.sortArticles(A, "newest").map(a => a.id), ["1", "2", "3"]);
  assert.deepStrictEqual(L.sortArticles(A, "oldest").map(a => a.id), ["3", "2", "1"]);
  assert.deepStrictEqual(L.sortArticles([A[2], A[1], A[0]], "priority").map(a => a.id), ["1", "2", "3"]);
});

test("top developments prefer recent high priority and fall back to 7 days", () => {
  const t = L.topDevelopments(A, NOW, 4);
  assert.strictEqual(t.windowDays, 2);
  assert.deepStrictEqual(t.items.map(a => a.id), ["1", "2"]);
  const later = L.topDevelopments(A, new Date("2026-11-20T00:00:00Z"), 4);
  assert.strictEqual(later.windowDays, 7);
  assert.strictEqual(L.topDevelopments([], NOW).items.length, 0);
});

test("metrics", () => {
  const m = L.computeMetrics(A, { last_successful_update: "2026-11-16T00:40:00Z", schedule_utc: ["30 0 * * *", "30 8 * * *"] }, NOW);
  assert.strictEqual(m.total, 3);
  assert.strictEqual(m.today, 1);
  assert.strictEqual(m.high, 1);
  assert.strictEqual(m.nextUpdate.toISOString(), "2026-11-16T08:30:00.000Z");
});

test("deriveRepo from GitHub Pages URL or meta", () => {
  assert.strictEqual(L.deriveRepo({ hostname: "manav.github.io", pathname: "/signal-intelligence/" }, null), "manav/signal-intelligence");
  assert.strictEqual(L.deriveRepo({ hostname: "manav.github.io", pathname: "/" }, null), "manav/manav.github.io");
  assert.strictEqual(L.deriveRepo({ hostname: "localhost", pathname: "/" }, { repository: "o/r" }), "o/r");
  assert.strictEqual(L.deriveRepo({ hostname: "localhost", pathname: "/" }, null), null);
});

test("short summary prefers AI summary and truncates", () => {
  assert.strictEqual(L.shortSummary(A[1]), "Template pricing changes for Indian businesses.");
  const long = { excerpt: "word ".repeat(100) };
  assert.ok(L.shortSummary(long, 50).endsWith("…"));
});

test("search matches word prefixes and phrases, not stray letters", () => {
  assert.deepStrictEqual(L.filterArticles(A, { query: "dmar" }, NOW).map(a => a.id), ["1"]);
  assert.deepStrictEqual(L.filterArticles(A, { query: "whatsapp pricing" }, NOW).map(a => a.id), ["2"]);
  assert.deepStrictEqual(L.filterArticles(A, { query: "  GOOGLE " }, NOW).map(a => a.id), ["1"]);
});
