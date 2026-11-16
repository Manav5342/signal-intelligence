/* Signal — newspaper front end. Static, no secrets: reads data/news.json published by GitHub Actions. */
(function () {
  "use strict";
  var L = window.SignalLib;
  var esc = L.escapeHtml;

  var DATA_URL = "data/news.json";
  var HEALTH_URL = "data/source_health.json";
  var SAVED_KEY = "signal.saved.v1";
  var DATELINE_CITY = "Mumbai";          // change to your city
  var PAGE_SIZE = 16;
  var CATEGORY_ORDER = ["ai", "b2b", "email", "whatsapp", "analytics", "martech"];
  var DEFAULT_CATEGORIES = { ai: "AI & Technology", b2b: "B2B Marketing", email: "Email Marketing",
    whatsapp: "WhatsApp Marketing", analytics: "Marketing Analytics", martech: "Marketing Technology" };
  var SHORT_NAMES = { ai: "AI & Tech", b2b: "B2B Marketing", email: "Email", whatsapp: "WhatsApp", analytics: "Analytics", martech: "Martech" };
  var BLANK_FILTERS = { query: "", category: "all", region: "all", date: "all", priority: "all", source: "all" };

  var state = {
    meta: null, articles: [], byId: {}, saved: loadSaved(), view: "front",
    filters: Object.assign({}, BLANK_FILTERS), sort: "newest", visible: PAGE_SIZE, loadError: null, polling: null
  };

  var $ = function (id) { return document.getElementById(id); };

  /* ---------- Saved articles (persist across sessions in this browser) ---------- */
  function loadSaved() {
    try {
      var parsed = JSON.parse(window.localStorage.getItem(SAVED_KEY) || "{}");
      return parsed && typeof parsed === "object" ? parsed : {};
    } catch (e) { return {}; }
  }
  function persistSaved() {
    try { window.localStorage.setItem(SAVED_KEY, JSON.stringify(state.saved)); }
    catch (e) { toast("This browser blocked storage, so saved articles can’t be kept."); }
  }
  function toggleSaved(id) {
    if (state.saved[id]) { delete state.saved[id]; toast("Removed from saved articles"); }
    else {
      var a = state.byId[id];
      if (!a) return;
      // Keep a full copy so it survives after the archive rotates the story out.
      state.saved[id] = Object.assign({}, a, { saved_at: new Date().toISOString() });
      toast("Saved");
    }
    persistSaved();
    render();
  }

  /* ---------- Data ---------- */
  function fetchJSON(url) {
    return fetch(url + "?t=" + Date.now(), { cache: "no-store" }).then(function (r) {
      if (!r.ok) throw new Error("the server answered HTTP " + r.status);
      return r.json();
    });
  }

  function load(opts) {
    opts = opts || {};
    if (!opts.silent) setLoading(true);
    return fetchJSON(DATA_URL).then(function (db) {
      if (!db || !Array.isArray(db.articles)) throw new Error("data/news.json isn’t in the expected format");
      var prev = state.meta && state.meta.last_successful_update;
      state.meta = db.meta || {};
      state.articles = db.articles.filter(function (a) { return a && a.id && L.safeUrl(a.url); });
      state.byId = {};
      state.articles.forEach(function (a) { state.byId[a.id] = a; });
      Object.keys(state.saved).forEach(function (id) {
        if (state.byId[id]) state.saved[id] = Object.assign({}, state.byId[id], { saved_at: state.saved[id].saved_at });
      });
      state.loadError = null;
      buildSelectOptions();
      render();
      if (opts.announce) toast(prev && prev !== state.meta.last_successful_update ? "New edition loaded" : "You have the latest edition");
      return state.meta.last_successful_update;
    }).catch(function (err) {
      state.loadError = err.message || String(err);
      render();
      if (opts.announce) toast("Couldn’t load the news: " + state.loadError);
    }).finally(function () { setLoading(false); });
  }

  function loadHealth() {
    fetchJSON(HEALTH_URL).then(function (h) {
      if (!h || !h.total) return;
      var failed = (h.sources || []).filter(function (s) { return !s.ok; });
      var txt = h.ok + " of " + h.total + " sources answered at the last check (" + L.formatDateTime(h.checked_at) + ").";
      if (failed.length) txt += " Not reachable: " + failed.map(function (s) { return s.name; }).join(", ") + ".";
      $("source-health").textContent = txt;
    }).catch(function () {});
  }

  /* ---------- Small building blocks ---------- */
  function categories() {
    var cats = (state.meta && state.meta.categories) || DEFAULT_CATEGORIES;
    return CATEGORY_ORDER.filter(function (k) { return cats[k]; }).map(function (k) { return { key: k, label: cats[k] }; });
  }
  function catLabel(key) { var c = categories().filter(function (x) { return x.key === key; })[0]; return c ? c.label : key; }

  function kicker(a) {
    var pri = a.priority || "Low";
    return '<p class="kicker"><span>' + esc(a.category_label || catLabel(a.category)) + '</span><span class="k-sep">/</span>' +
      '<span class="' + (a.region === "India" ? "k-region" : "muted") + '">' + esc(a.region || "Global") + "</span>" +
      '<span class="k-sep">/</span><span class="' + (pri === "High" ? "k-priority" : "muted") + '">' + esc(pri) + " priority</span></p>";
  }

  function byline(a) {
    return '<p class="byline"><span class="pub">' + esc(a.source) + "</span>" + (a.via ? ' <span>via ' + esc(a.via.replace(/^Google News:?\s*/, "Google News")) + "</span>" : "") +
      ', <time datetime="' + esc(a.published_at) + '" title="Original publication date">' + esc(L.formatDate(a.published_at)) + "</time></p>";
  }

  function headline(a) {
    return '<button data-action="open" data-id="' + esc(a.id) + '">' + esc(a.title) + "</button>";
  }

  function saveButton(a) {
    var saved = !!state.saved[a.id];
    return '<button class="save-btn' + (saved ? " is-saved" : "") + '" data-action="save" data-id="' + esc(a.id) + '" aria-pressed="' + saved + '">' +
      '<svg width="12" height="14" viewBox="0 0 12 14" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round" aria-hidden="true"><path d="M1 1h10v12L6 9.6 1 13z"/></svg>' +
      (saved ? "Saved" : "Save") + "</button>";
  }

  function actions(a) {
    var url = L.safeUrl(a.url);
    return '<div class="story-actions">' +
      '<button class="act-link" data-action="open" data-id="' + esc(a.id) + '">' + (L.hasAnalysis(a) ? "Read analysis" : "Details") + "</button>" +
      (url ? '<a href="' + esc(url) + '" target="_blank" rel="noopener noreferrer nofollow">Original source<span class="sr-only"> (opens in a new tab)</span></a>' : "") +
      saveButton(a) + "</div>";
  }

  function dek(a, limit) {
    var text = L.shortSummary(a, limit);
    if (!text) return '<p class="dek muted">The feed carried no excerpt. Open the original for details.</p>';
    return '<p class="dek">' + (L.hasAnalysis(a) ? "" : '<span class="excerpt-note">From the publisher: </span>') + esc(text) + "</p>";
  }

  function emptyState(title, body, action) {
    return '<div class="empty"><h3>' + esc(title) + "</h3><p>" + body + "</p>" + (action || "") + "</div>";
  }

  function setLoading(on) {
    document.body.classList.toggle("is-loading", on);
    if (on && !state.articles.length) {
      var sk = "";
      for (var i = 0; i < 4; i++) sk += '<div class="story skeleton" aria-hidden="true"><span></span><span></span><span></span></div>';
      $("latest-list").innerHTML = sk;
    }
  }

  /* ---------- Masthead, nav, index ---------- */
  function renderMasthead() {
    var now = new Date();
    var longDate = new Intl.DateTimeFormat("en-GB", { timeZone: L.TZ, weekday: "long", day: "numeric", month: "long", year: "numeric" }).format(now);
    var shortDate = new Intl.DateTimeFormat("en-GB", { timeZone: L.TZ, weekday: "short", day: "numeric", month: "short" }).format(now);
    $("dateline").innerHTML = '<span class="d-long">' + esc(DATELINE_CITY + ", " + longDate) + '</span><span class="d-short">' + esc(DATELINE_CITY + ", " + shortDate) + "</span>";
    var last = state.meta && state.meta.last_successful_update;
    var ear = $("edition-ear");
    $("edition-name").textContent = L.editionName(last) || "First edition pending";
    $("edition-sub").textContent = last ? "Updated " + L.formatDateTime(last) : "Printed at 6 am and 2 pm IST";
    var stale = last && (Date.now() - new Date(last).getTime() > 20 * 3600000);
    ear.classList.toggle("is-stale", !!stale);
  }

  function renderNav() {
    var f = state.filters;
    var items = [{ href: "#/", label: "Front page", active: state.view === "front" && !filtersActive() }];
    categories().forEach(function (c) {
      items.push({ href: "#/category/" + c.key, label: c.label, active: state.view === "front" && f.category === c.key });
    });
    items.push({ href: "#/region/India", label: "India", active: state.view === "front" && f.region === "India" && f.category === "all" });
    items.push({ href: "#/saved", label: "Saved", active: state.view === "saved" });
    $("section-nav").innerHTML = items.map(function (i) {
      return '<li><a href="' + i.href + '"' + (i.active ? ' aria-current="page"' : "") + ">" + esc(i.label) + "</a></li>";
    }).join("");
    var count = Object.keys(state.saved).length;
    $("saved-count").textContent = count;
    document.querySelector('.u-link[data-route="saved"]').classList.toggle("is-active", state.view === "saved");
  }

  function renderMetrics() {
    var m = L.computeMetrics(state.articles, state.meta, new Date());
    $("m-total").textContent = m.total;
    $("m-today").textContent = m.today;
    $("m-high").textContent = m.high;
    $("m-last").textContent = m.lastUpdate ? L.relativeTime(m.lastUpdate) : "not yet";
    $("m-last").title = m.lastUpdate ? L.formatDateTime(m.lastUpdate) : "";
    $("m-next").textContent = m.nextUpdate ? L.formatTime(m.nextUpdate) : "–";
    $("m-next").title = "GitHub can start scheduled runs a few minutes late";
    $("metrics").hidden = state.view === "saved";
  }

  function renderNotice() {
    var n = $("notice"), meta = state.meta || {}, run = meta.last_run || {};
    var msgs = [];
    if (state.loadError) msgs.push("The news couldn’t be loaded because " + esc(state.loadError) + ". If you opened index.html straight from your computer, open the GitHub Pages address instead, or run a local server.");
    else {
      if (run.status === "failed") msgs.push("The last collection couldn’t reach any source, so this is the previous edition.");
      else if (run.status === "partial" && run.sources_failed) msgs.push(run.sources_failed + " of " + run.sources_total + " sources didn’t answer during the last collection. Everything else was updated.");
      if (meta.last_successful_update && meta.ai_enabled === false) msgs.push("AI analysis is off because the <code>OPENAI_API_KEY</code> secret isn’t set. Stories show the publisher’s excerpt and rule-based sections.");
    }
    n.hidden = !msgs.length;
    n.innerHTML = msgs.map(function (m) { return "<p>" + m + "</p>"; }).join("");
  }

  function buildSelectOptions() {
    var sel = $("f-source"), current = state.filters.source, counts = {};
    state.articles.forEach(function (a) { counts[a.source] = (counts[a.source] || 0) + 1; });
    var names = Object.keys(counts).sort(function (a, b) { return a.localeCompare(b); });
    sel.innerHTML = '<option value="all">All publishers</option>' + names.map(function (s) {
      return '<option value="' + esc(s) + '">' + esc(s) + " (" + counts[s] + ")</option>";
    }).join("");
    sel.value = names.indexOf(current) >= 0 ? current : "all";
    state.filters.source = sel.value;
    $("f-category").innerHTML = '<option value="all">All sections</option>' + categories().map(function (c) {
      return '<option value="' + c.key + '">' + esc(c.label) + "</option>";
    }).join("");
  }

  function syncControls() {
    var f = state.filters;
    if ($("search").value !== f.query) $("search").value = f.query;
    $("f-category").value = f.category; $("f-date").value = f.date; $("f-priority").value = f.priority;
    $("f-source").value = f.source; $("f-sort").value = state.sort;
    Array.prototype.forEach.call(document.querySelectorAll("#region-seg button"), function (b) {
      b.setAttribute("aria-pressed", String(b.dataset.region === f.region));
    });
    $("clear-filters").hidden = !filtersActive();
  }

  function filtersActive() {
    var f = state.filters;
    return !!(f.query || f.category !== "all" || f.region !== "all" || f.date !== "all" || f.priority !== "all" || f.source !== "all");
  }

  /* ---------- Front page ---------- */
  function renderFront() {
    var front = $("top-section");
    var show = state.view === "front" && !filtersActive() && !state.loadError && state.articles.length > 0;
    front.hidden = !show;
    if (!show) return;
    var t = L.topDevelopments(state.articles, new Date(), 5);
    if (!t.items.length) { front.hidden = true; return; }
    var lead = t.items[0], an = lead.analysis || {};
    var body = "";
    if (L.hasAnalysis(lead)) {
      body = '<div class="lead-body"><p><span class="label">Why it matters</span>' + esc(an.why_it_matters) + "</p>" +
        ((an.recommendations || [])[0] ? '<p><span class="label">What to do next</span>' + esc(an.recommendations[0]) + "</p>" : "") + "</div>";
    }
    $("lead-story").innerHTML = '<article data-id="' + esc(lead.id) + '">' + kicker(lead) +
      '<h2 class="hl">' + headline(lead) + "</h2>" + dek(lead, 360) + byline(lead) + body + actions(lead) + "</article>";
    $("top-title").textContent = t.windowDays <= 2 ? "Today’s top developments" : "This week’s top developments";
    var rest = t.items.slice(1);
    $("top-list").innerHTML = rest.length ? rest.map(function (a) {
      return '<article class="rail-story" data-id="' + esc(a.id) + '">' + kicker(a) + '<h3 class="hl">' + headline(a) + "</h3>" + dek(a, 150) + byline(a) + "</article>";
    }).join("") : '<p class="dek muted">Only one major development so far. See the latest stories below.</p>';
  }

  function renderDesks() {
    var desks = $("desks-section");
    var show = state.view === "front" && !filtersActive() && !state.loadError && state.articles.length > 0;
    desks.hidden = !show;
    if (!show) return;
    var fronts = L.sectionFronts(state.articles, categories().map(function (c) { return c.key; }), 3);
    $("desk-grid").innerHTML = fronts.map(function (s) {
      return '<section class="desk"><div class="desk-head"><h3>' + esc(catLabel(s.key)) + '</h3><a href="#/category/' + s.key + '">All ' + s.total + (s.total === 1 ? " story" : " stories") + "</a></div><ol>" +
        s.items.map(function (a) { return '<li><h4 class="hl">' + headline(a) + "</h4>" + byline(a) + "</li>"; }).join("") + "</ol></section>";
    }).join("");
  }

  /* ---------- Story columns ---------- */
  function renderLatest() {
    var isSaved = state.view === "saved";
    var pool = isSaved ? Object.keys(state.saved).map(function (k) { return state.saved[k]; }) : state.articles;
    var filtered = L.sortArticles(L.filterArticles(pool, state.filters), state.sort);
    var f = state.filters, list = $("latest-list");

    var title = "Latest Intelligence";
    if (isSaved) title = "Saved articles";
    else if (f.category !== "all" && !f.query) title = catLabel(f.category);
    else if (f.region === "India" && !f.query && f.category === "all") title = "India";
    else if (f.query) title = "Search results";
    $("latest-title").textContent = title;

    if (state.loadError) {
      list.innerHTML = emptyState("This edition didn’t arrive", "Signal couldn’t load the news because " + esc(state.loadError) + ".", '<button class="btn btn-outline" data-action="reload">Try again</button>');
    } else if (!pool.length) {
      list.innerHTML = isSaved
        ? emptyState("Nothing saved yet", "Choose Save under any story to keep it here. Saved stories stay in this browser, even after they leave the archive.")
        : emptyState("The first edition hasn’t been printed", "Signal fills up after its first collection, which runs automatically at 6 am and 2 pm IST. To start one now, choose <strong>Refresh</strong> and then <strong>Open the workflow on GitHub</strong>.");
    } else if (!filtered.length) {
      list.innerHTML = emptyState("No stories match", "Try a different word, or clear the filters to see everything.", '<button class="btn btn-outline" data-action="clear">Clear filters</button>');
    } else {
      list.innerHTML = filtered.slice(0, state.visible).map(function (a) {
        return '<article class="story' + (a.priority === "High" ? " is-high" : "") + '" data-id="' + esc(a.id) + '">' + kicker(a) +
          '<h3 class="hl">' + headline(a) + "</h3>" + dek(a, 190) + byline(a) + actions(a) + "</article>";
      }).join("");
    }
    $("show-more").hidden = filtered.length <= state.visible;
    var sortName = { newest: "newest first", oldest: "oldest first", priority: "highest priority first" }[state.sort];
    $("latest-sub").textContent = pool.length && !state.loadError ? filtered.length + (filtered.length === 1 ? " story" : " stories") + ", " + sortName : "";
  }

  function render() {
    renderMasthead();
    renderNav();
    renderMetrics();
    renderNotice();
    syncControls();
    renderFront();
    renderLatest();
    renderDesks();
  }

  /* ---------- Article reader ---------- */
  function bullets(items) {
    return "<ul>" + items.map(function (i) { return "<li>" + esc(i) + "</li>"; }).join("") + "</ul>";
  }

  function openArticle(id) {
    var a = state.byId[id] || state.saved[id];
    if (!a) return;
    var an = a.analysis || {}, url = L.safeUrl(a.url), saved = !!state.saved[a.id];
    var html = kicker(a) + '<h2 class="hl" id="modal-title">' + esc(a.title) + "</h2>" +
      '<div class="byline"><span><span class="pub">' + esc(a.source) + "</span>" + (a.via ? " via " + esc(a.via) : "") + "</span>" +
      '<span>Published <time datetime="' + esc(a.published_at) + '">' + esc(L.formatDateTime(a.published_at)) + "</time></span></div>";

    if (an.status === "complete") {
      if (an.needs_validation) html += '<p class="callout"><strong>Check before acting.</strong> ' + esc(an.validation_note || "The source text was limited, so confirm the details in the original article.") + "</p>";
      var evidence = an.evidence === "headline_only" ? "the headline only" : an.evidence === "feed_excerpt" ? "the feed excerpt" : "the feed text";
      html += '<section class="reported"><h3>What ' + esc(a.source) + " reported</h3><p>" + esc(an.reported_facts || a.excerpt || "") + '</p><p class="fine">Facts as stated in ' + evidence + " the publisher syndicated.</p></section>";
      html += '<p class="analysis-mark"><span><strong>Signal analysis.</strong> Written by AI; interpretation, not reported fact.</span></p>';
      html += '<div class="reader-summary"><p>' + esc(an.summary) + "</p></div>";
      html += '<section class="pull"><h3>Why this matters</h3><p>' + esc(an.why_it_matters) + "</p></section>";
      var cols = "";
      if ((an.applications || []).length) cols += '<section class="reader-section"><h3>Practical marketing applications</h3>' + bullets(an.applications) + "</section>";
      if ((an.recommendations || []).length) cols += '<section class="reader-section"><h3>Strategic recommendations</h3>' + bullets(an.recommendations) + "</section>";
      if (cols) html += '<div class="reader-cols">' + cols + "</div>";
      html += '<dl class="facts"><dt>Priority</dt><dd>' + esc(a.priority) + (an.priority_reason ? ". " + esc(an.priority_reason) : "") + "</dd>" +
        "<dt>Region</dt><dd>" + esc(a.region) + (a.region_reason ? ". " + esc(a.region_reason) : "") + "</dd>" +
        ((a.companies || []).length ? "<dt>Companies</dt><dd>" + esc(a.companies.join(", ")) + "</dd>" : "") +
        ((a.topics || []).length ? "<dt>Topics</dt><dd>" + esc(a.topics.join(", ")) + "</dd>" : "") +
        "<dt>Analysis</dt><dd>" + esc(an.model || "AI") + ", " + esc(L.formatDateTime(an.generated_at)) + "</dd></dl>";
    } else {
      var reason = an.status === "skipped_no_key" ? "AI analysis is off because no OpenAI API key is set for this site."
        : an.status === "failed" ? "AI analysis failed for this story. It will be tried again at the next collection."
        : "AI analysis is queued for the next collection.";
      html += '<p class="callout plain">' + esc(reason) + "</p>";
      html += '<section class="reported"><h3>From the publisher</h3><p>' + (a.excerpt ? esc(a.excerpt) : '<span class="muted">The feed carried no excerpt.</span>') + "</p></section>";
      html += '<dl class="facts"><dt>Region</dt><dd>' + esc(a.region) + (a.region_reason ? ". " + esc(a.region_reason) : "") + "</dd><dt>Sorted by</dt><dd>Keyword and source rules</dd></dl>";
    }

    if ((a.also_covered_by || []).length) {
      html += '<section class="covered"><h3>Also covered by</h3><ul>' + a.also_covered_by.map(function (c) {
        var cu = L.safeUrl(c.url);
        return "<li>" + (cu ? '<a href="' + esc(cu) + '" target="_blank" rel="noopener noreferrer nofollow">' + esc(c.source || "Another publisher") + "</a>" : esc(c.source)) + (c.title ? ' <span class="muted">' + esc(c.title) + "</span>" : "") + "</li>";
      }).join("") + "</ul></section>";
    }

    html += '<div class="reader-actions">' +
      (url ? '<a class="btn btn-ink" href="' + esc(url) + '" target="_blank" rel="noopener noreferrer nofollow">Read the original at ' + esc(a.source) + "</a>" : "") +
      '<button class="btn btn-outline" data-action="save" data-id="' + esc(a.id) + '" aria-pressed="' + saved + '">' + (saved ? "Saved" : "Save article") + "</button></div>";
    if (a.url_check === "restricted") html += '<p class="fine">This publisher blocks automated link checks, so the link couldn’t be fully verified.</p>';

    $("modal-body").innerHTML = html;
    var dlg = $("article-modal");
    dlg.dataset.id = a.id;
    if (typeof dlg.showModal === "function") { if (!dlg.open) dlg.showModal(); } else dlg.setAttribute("open", "");
    document.body.classList.add("modal-open");
    dlg.querySelector(".reader").scrollTop = 0;
    $("modal-close").focus();
  }

  function closeModal() {
    var dlg = $("article-modal");
    if (dlg.open) { if (typeof dlg.close === "function") dlg.close(); else dlg.removeAttribute("open"); }
    document.body.classList.remove("modal-open");
  }

  /* ---------- Refresh ---------- */
  function setupWorkflowLink() {
    var repo = L.deriveRepo(window.location, state.meta);
    var link = $("run-workflow-link"), note = $("run-workflow-note");
    if (repo) {
      link.href = "https://github.com/" + repo + "/actions/workflows/refresh-news.yml";
      link.removeAttribute("aria-disabled");
      note.textContent = "Only people with write access to " + repo + " can start it. This page stores no token.";
    } else {
      link.removeAttribute("href");
      link.setAttribute("aria-disabled", "true");
      note.textContent = "Open Signal from its GitHub Pages address to use this.";
    }
  }

  function startPolling() {
    if (state.polling) clearInterval(state.polling);
    var startedFrom = state.meta && state.meta.last_successful_update, tries = 0;
    toast("Watching for the new edition. This page updates when it’s ready.");
    state.polling = setInterval(function () {
      tries++;
      load({ silent: true }).then(function (ts) {
        if (ts && ts !== startedFrom) { clearInterval(state.polling); state.polling = null; toast("The new edition is here"); }
        else if (tries >= 15) { clearInterval(state.polling); state.polling = null; toast("No new edition yet. Check the workflow on GitHub."); }
      });
    }, 60000);
  }

  function togglePanel(force) {
    var panel = $("refresh-panel"), btn = $("refresh-btn");
    var open = force !== undefined ? force : panel.hidden;
    panel.hidden = !open;
    btn.setAttribute("aria-expanded", String(open));
  }

  var toastTimer;
  function toast(msg) {
    var t = $("toast");
    t.textContent = msg; t.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { t.hidden = true; }, 3400);
  }

  /* ---------- Routing: #/, #/category/<key>, #/region/India, #/saved ---------- */
  function route() {
    var h = window.location.hash || "#/";
    var cat = h.match(/^#\/category\/(\w+)/), reg = h.match(/^#\/region\/(India|Global)/);
    if (h.indexOf("#/saved") === 0) state.view = "saved";
    else {
      state.view = "front";
      if (cat) { state.filters.category = cat[1]; state.filters.region = "all"; }
      else if (reg) { state.filters.region = reg[1]; state.filters.category = "all"; }
      else if (h === "#/" || h === "#") { state.filters.category = "all"; if (state.filters.region !== "Global") state.filters.region = "all"; }
    }
    state.visible = PAGE_SIZE;
    render();
    if (cat || reg || h.indexOf("#/saved") === 0) $("main").scrollIntoView({ block: "start" });
  }

  function setFilter(key, value) {
    state.filters[key] = value;
    state.visible = PAGE_SIZE;
    if (state.view === "front") {
      var f = state.filters, target = "#/";
      if (f.category !== "all") target = "#/category/" + f.category;
      else if (f.region === "India") target = "#/region/India";
      if (window.location.hash !== target && !(target === "#/" && !window.location.hash)) history.replaceState(null, "", target);
    }
    render();
  }

  function clearFilters() {
    state.filters = Object.assign({}, BLANK_FILTERS);
    state.visible = PAGE_SIZE;
    if (/^#\/(category|region)/.test(window.location.hash)) history.replaceState(null, "", "#/");
    render();
  }

  /* ---------- Events ---------- */
  function bind() {
    var debounce;
    $("search").addEventListener("input", function (e) {
      clearTimeout(debounce);
      debounce = setTimeout(function () { state.filters.query = e.target.value; state.visible = PAGE_SIZE; render(); }, 160);
    });
    [["f-category", "category"], ["f-date", "date"], ["f-priority", "priority"], ["f-source", "source"]].forEach(function (p) {
      $(p[0]).addEventListener("change", function (e) { setFilter(p[1], e.target.value); });
    });
    $("f-sort").addEventListener("change", function (e) { state.sort = e.target.value; renderLatest(); });
    $("region-seg").addEventListener("click", function (e) {
      var b = e.target.closest("button[data-region]");
      if (b) setFilter("region", b.dataset.region);
    });
    $("refresh-btn").addEventListener("click", function (e) { e.stopPropagation(); togglePanel(); });
    $("refresh-panel").addEventListener("click", function (e) { e.stopPropagation(); });
    document.addEventListener("click", function () { togglePanel(false); });
    $("reload-data-btn").addEventListener("click", function () { togglePanel(false); load({ announce: true }); loadHealth(); });
    $("run-workflow-link").addEventListener("click", function (e) {
      if (this.getAttribute("aria-disabled") === "true") { e.preventDefault(); return; }
      togglePanel(false);
      startPolling();
    });
    $("clear-filters").addEventListener("click", clearFilters);
    $("show-more").addEventListener("click", function () { state.visible += PAGE_SIZE; renderLatest(); });

    document.addEventListener("click", function (e) {
      var el = e.target.closest("[data-action]");
      if (!el) return;
      var action = el.dataset.action;
      if (action === "open") openArticle(el.dataset.id);
      else if (action === "save") { toggleSaved(el.dataset.id); if ($("article-modal").open) openArticle(el.dataset.id); }
      else if (action === "clear") clearFilters();
      else if (action === "reload") load({ announce: true });
    });

    var dlg = $("article-modal");
    $("modal-close").addEventListener("click", closeModal);
    dlg.addEventListener("click", function (e) { if (e.target === dlg) closeModal(); });
    dlg.addEventListener("close", function () { document.body.classList.remove("modal-open"); });
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape") togglePanel(false);
      if (e.key === "/" && !/INPUT|SELECT|TEXTAREA/.test(document.activeElement.tagName) && !dlg.open) { e.preventDefault(); $("search").focus(); }
    });
    window.addEventListener("hashchange", route);
    window.addEventListener("storage", function (e) { if (e.key === SAVED_KEY) { state.saved = loadSaved(); render(); } });
    setInterval(function () { renderMetrics(); renderMasthead(); }, 60000);
  }

  function init() {
    buildSelectOptions();
    bind();
    route();
    load().then(setupWorkflowLink);
    setupWorkflowLink();
    loadHealth();
  }

  init();
})();
