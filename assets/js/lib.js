/* Signal — pure helpers (no DOM). Loaded in the browser as window.SignalLib and
   in Node tests via require(). */
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory();
  else root.SignalLib = factory();
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  var TZ = "Asia/Kolkata";
  var PRIORITY_WEIGHT = { High: 3, Medium: 2, Low: 1 };
  var DAY = 86400000;

  function escapeHtml(value) {
    return String(value == null ? "" : value)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }

  function safeUrl(url) {
    try {
      var u = new URL(String(url));
      return u.protocol === "https:" || u.protocol === "http:" ? u.href : null;
    } catch (e) { return null; }
  }

  function parseDate(iso) {
    var d = iso ? new Date(iso) : null;
    return d && !isNaN(d.getTime()) ? d : null;
  }

  /* Calendar day key in IST, e.g. "2026-11-16". */
  function istDayKey(date) {
    return new Intl.DateTimeFormat("en-CA", { timeZone: TZ, year: "numeric", month: "2-digit", day: "2-digit" }).format(date);
  }

  function isTodayIST(iso, now) {
    var d = parseDate(iso);
    return !!d && istDayKey(d) === istDayKey(now || new Date());
  }

  function formatDate(iso, opts) {
    var d = parseDate(iso);
    if (!d) return "Unknown date";
    return new Intl.DateTimeFormat("en-IN", Object.assign({ timeZone: TZ, day: "numeric", month: "short", year: "numeric" }, opts || {})).format(d);
  }

  function formatDateTime(iso) {
    return formatDate(iso, { hour: "numeric", minute: "2-digit", hour12: true }) + " IST";
  }

  function relativeTime(iso, now) {
    var d = parseDate(iso);
    if (!d) return "never";
    var diff = (now || new Date()).getTime() - d.getTime();
    var mins = Math.round(diff / 60000);
    if (mins < 1) return "just now";
    if (mins < 60) return mins + " min ago";
    var hrs = Math.round(mins / 60);
    if (hrs < 24) return hrs + (hrs === 1 ? " hr ago" : " hrs ago");
    var days = Math.round(hrs / 24);
    return days + (days === 1 ? " day ago" : " days ago");
  }

  /* Parse "M H * * *" cron strings (daily schedules only) and return the next run. */
  function nextScheduledRun(now, schedules) {
    now = now || new Date();
    schedules = schedules && schedules.length ? schedules : ["30 0 * * *", "30 8 * * *"];
    var best = null;
    schedules.forEach(function (cron) {
      var parts = String(cron).trim().split(/\s+/);
      var m = parseInt(parts[0], 10), h = parseInt(parts[1], 10);
      if (isNaN(m) || isNaN(h)) return;
      for (var add = 0; add < 2; add++) {
        var c = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate() + add, h, m));
        if (c > now && (!best || c < best)) { best = c; break; }
      }
    });
    return best;
  }

  function searchText(a) {
    var an = a.analysis || {};
    return [a.title, a.source, a.via, a.category_label, a.region, a.excerpt, an.summary,
      (a.companies || []).join(" "), (a.topics || []).join(" ")].join(" ").toLowerCase();
  }

  /* Whole phrase anywhere, or every term at the start of a word ("dmarc", "hub" -> HubSpot). */
  function matchesQuery(a, phrase, terms) {
    var hay = searchText(a);
    if (hay.indexOf(phrase) !== -1) return true;
    var words = " " + hay.replace(/[^\p{L}\p{N}]+/gu, " ");
    for (var i = 0; i < terms.length; i++) if (words.indexOf(" " + terms[i]) === -1) return false;
    return true;
  }

  function filterArticles(list, f, now) {
    f = f || {};
    now = now || new Date();
    var phrase = String(f.query || "").toLowerCase().trim();
    var terms = phrase.split(/[^\p{L}\p{N}]+/u).filter(Boolean);
    return list.filter(function (a) {
      if (f.category && f.category !== "all" && a.category !== f.category) return false;
      if (f.region && f.region !== "all" && a.region !== f.region) return false;
      if (f.priority && f.priority !== "all" && a.priority !== f.priority) return false;
      if (f.source && f.source !== "all" && a.source !== f.source) return false;
      if (f.date && f.date !== "all") {
        var d = parseDate(a.published_at);
        if (!d) return false;
        if (f.date === "today") { if (!isTodayIST(a.published_at, now)) return false; }
        else {
          var days = parseInt(f.date, 10);
          if (!isNaN(days) && now - d > days * DAY) return false;
        }
      }
      if (phrase && !matchesQuery(a, phrase, terms)) return false;
      return true;
    });
  }

  function time(a) { var d = parseDate(a.published_at); return d ? d.getTime() : 0; }

  function sortArticles(list, mode) {
    var out = list.slice();
    if (mode === "oldest") out.sort(function (a, b) { return time(a) - time(b); });
    else if (mode === "priority") out.sort(function (a, b) {
      return (PRIORITY_WEIGHT[b.priority] || 0) - (PRIORITY_WEIGHT[a.priority] || 0) ||
        (b.priority_score || 0) - (a.priority_score || 0) || time(b) - time(a);
    });
    else out.sort(function (a, b) { return time(b) - time(a); });
    return out;
  }

  function richness(a) {
    var an = a.analysis || {};
    if (an.status === "complete" && !an.needs_validation) return 3;
    if (an.status === "complete") return 2;
    return a.excerpt ? 1 : 0;
  }

  /* Most important recent developments across categories: newest 48h by priority,
     at most 2 per category so one topic can't crowd out the rest. */
  function topDevelopments(list, now, n) {
    now = now || new Date();
    n = n || 4;
    var windows = [2, 7];
    for (var w = 0; w < windows.length; w++) {
      var recent = list.filter(function (a) { return now - time(a) <= windows[w] * DAY; });
      // Within a priority level, prefer stories with real substance (analysis, then
      // publisher text) so the front page never leads with a bare headline.
      var ranked = recent.slice().sort(function (a, b) {
        return (PRIORITY_WEIGHT[b.priority] || 0) - (PRIORITY_WEIGHT[a.priority] || 0) ||
          richness(b) - richness(a) || (b.priority_score || 0) - (a.priority_score || 0) || time(b) - time(a);
      });
      var perCat = {}, picks = [];
      ranked.forEach(function (a) {
        if (picks.length >= n) return;
        perCat[a.category] = (perCat[a.category] || 0) + 1;
        if (perCat[a.category] <= 2) picks.push(a);
      });
      if (picks.length) return { items: picks, windowDays: windows[w] };
    }
    return { items: [], windowDays: 7 };
  }

  function shortSummary(a, limit) {
    limit = limit || 220;
    var an = a.analysis || {};
    var text = (an.status === "complete" && an.summary) ? an.summary : (a.excerpt || "");
    if (text.length <= limit) return text;
    return text.slice(0, limit).replace(/\s+\S*$/, "") + "…";
  }

  function hasAnalysis(a) { return !!(a.analysis && a.analysis.status === "complete"); }

  /* owner/repo for the Actions link: meta.repository, else *.github.io/<repo>/ */
  function deriveRepo(loc, meta) {
    if (meta && meta.repository && /^[\w.-]+\/[\w.-]+$/.test(meta.repository)) return meta.repository;
    if (!loc || !loc.hostname) return null;
    var m = loc.hostname.match(/^([\w-]+)\.github\.io$/i);
    if (!m) return null;
    var seg = (loc.pathname || "/").split("/").filter(Boolean)[0];
    return m[1] + "/" + (seg || (m[1] + ".github.io"));
  }

  function computeMetrics(list, meta, now) {
    now = now || new Date();
    return {
      total: list.length,
      today: list.filter(function (a) { return isTodayIST(a.published_at, now); }).length,
      high: list.filter(function (a) { return a.priority === "High"; }).length,
      lastUpdate: meta && meta.last_successful_update,
      nextUpdate: nextScheduledRun(now, meta && meta.schedule_utc)
    };
  }

  /* Which edition the published data represents: runs finishing before noon IST are the
     morning edition (06:00 run), later ones the afternoon edition (14:00 run). */
  function editionName(lastUpdateIso) {
    var d = parseDate(lastUpdateIso);
    if (!d) return null;
    var hour = parseInt(new Intl.DateTimeFormat("en-GB", { timeZone: TZ, hour: "2-digit", hour12: false }).format(d), 10);
    return hour < 12 ? "Morning edition" : "Afternoon edition";
  }

  /* Up to n stories per category, newest high-priority first: the "section fronts". */
  function sectionFronts(list, categoryKeys, n) {
    n = n || 3;
    return categoryKeys.map(function (key) {
      var items = list.filter(function (a) { return a.category === key; });
      var recent = sortArticles(items, "newest").slice(0, 12);
      return { key: key, total: items.length, items: sortArticles(recent, "priority").slice(0, n) };
    }).filter(function (s) { return s.total > 0; });
  }

  function formatTime(date) {
    return new Intl.DateTimeFormat("en-IN", { timeZone: TZ, hour: "numeric", minute: "2-digit", hour12: true }).format(date).replace(/\s?(am|pm)$/i, function (m) { return " " + m.trim().toLowerCase(); }) + " IST";
  }

  return {
    editionName: editionName, sectionFronts: sectionFronts, formatTime: formatTime,
    richness: richness, TZ: TZ, escapeHtml: escapeHtml, safeUrl: safeUrl, parseDate: parseDate, isTodayIST: isTodayIST,
    formatDate: formatDate, formatDateTime: formatDateTime, relativeTime: relativeTime,
    nextScheduledRun: nextScheduledRun, filterArticles: filterArticles, sortArticles: sortArticles,
    topDevelopments: topDevelopments, shortSummary: shortSummary, hasAnalysis: hasAnalysis,
    deriveRepo: deriveRepo, computeMetrics: computeMetrics, searchText: searchText
  };
});
