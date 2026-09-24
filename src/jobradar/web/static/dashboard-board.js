/* JobRadar dashboard — The board: tabs, the Today queue and the Filtered-out panel.
   Plain scripts sharing one global scope, loaded in order by dashboard.html. */

/* --------------------------------------------------------------------------
   The board
-------------------------------------------------------------------------- */
/* Panel tabs are not lists of jobs, so they render their own thing and the
   board is hidden for them. "Today" is first because a board with two hundred
   jobs does not say where to start. */
/* Looked up when the tab opens, not when this file loads: panels may live in
   files loaded after this one. */
const PANELS = {
  today: () => renderToday(),
  filtered: () => renderFiltered(),
  insights: () => renderInsights(),
};

const TABS = [
  ["today",     "Today",     j => j.status === "active" && !j.closed],
  ["active",    "Active",    j => j.status === "active" && !j.closed],
  ["applied",   "Applied",   j => j.status === "applied" && j.stage !== "rejected"],
  ["rejected",  "Rejected",  j => j.status === "applied" && j.stage === "rejected"],
  ["discarded", "Discarded", j => j.status === "discarded"],
  ["closed",    "Closed ads", j => j.closed && j.status === "active"],
  ["filtered",  "Filtered out", () => false],
  ["insights",  "Insights", () => false],
];

function tabCount(key, predicate) {
  if (key === "filtered") return (STATE.filtered || []).length;
  if (key === "insights") return STATE.jobs.filter(j => j.status === "applied").length;
  if (key === "today") return Math.max(0, weeklyGoal() - appliedThisWeek());
  return STATE.jobs.filter(predicate).length;
}

function render() {
  const tabs = $("#tabs");
  tabs.innerHTML = "";
  for (const [key, title, predicate] of TABS) {
    const node = el("button", { role: "tab" }, `${title} (${tabCount(key, predicate)})`);
    node.setAttribute("aria-selected", key === TAB);
    node.onclick = () => { TAB = key; render(); };
    tabs.append(node);
  }

  const board = $("#board");
  board.innerHTML = "";
  $("#job-count").textContent = `${STATE.jobs.length} jobs tracked`;
  $("#btn-mail").hidden = !(STATE.settings.mail && STATE.settings.mail.enabled);
  const last = STATE.runs[0];
  $("#run-note").textContent = last
    ? `Last run: ${last.kept} kept of ${last.fetched} fetched, ${last.new} new.` : "";

  const isPanel = Object.prototype.hasOwnProperty.call(PANELS, TAB);
  $("#toolbar").hidden = isPanel;
  selectionBar();
  if ($("#selection-bar")) $("#selection-bar").hidden = isPanel || !SELECTED.size;
  if (isPanel) { board.append(PANELS[TAB]()); return; }

  const predicate = TABS.find(t => t[0] === TAB)[2];
  const needle = $("#filter").value.trim().toLowerCase();
  let jobs = STATE.jobs.filter(predicate);
  if (needle) {
    jobs = jobs.filter(job =>
      `${job.title} ${job.company} ${job.strengths.join(" ")} ${job.requirements.join(" ")}`
        .toLowerCase().includes(needle));
  }
  const sort = $("#sort").value;
  jobs.sort((a, b) =>
    sort === "date" ? String(b.posted_at || "").localeCompare(String(a.posted_at || "")) :
    sort === "salary" ? (b.salary_max || 0) - (a.salary_max || 0) :
    sort === "score" ? b.score_tailored - a.score_tailored :
    b.focus - a.focus);

  if (TAB === "applied") {
    const orphans = orphansBlock();
    if (orphans) board.append(orphans);
  }
  if (!jobs.length) {
    board.append(el("div", { className: "empty" },
      STATE.jobs.length ? "Nothing in this tab." :
      "No jobs yet. Press \u201cSearch now\u201d to run the first search."));
  } else {
    jobs.forEach(job => board.append(jobCard(job)));
  }
}

/* --------------------------------------------------------------------------
   Today: the short queue
   A board is a list; it does not say where to start. This is six jobs in focus
   order and a weekly counter, which is the smallest thing that turns a board
   into a session of work.
-------------------------------------------------------------------------- */
const weeklyGoal = () => (STATE.settings && STATE.settings.weekly_goal) || 10;
const queueSize = () => (STATE.settings && STATE.settings.today_queue_size) || 6;

function mondayOfThisWeek() {
  const now = new Date();
  const day = (now.getDay() + 6) % 7;          // Monday = 0
  const monday = new Date(now.getFullYear(), now.getMonth(), now.getDate() - day);
  return localDateString(monday);
}

function appliedThisWeek() {
  const since = mondayOfThisWeek();
  return STATE.jobs.filter(j => j.status === "applied" && j.applied_on && j.applied_on >= since).length;
}

function renderToday() {
  const panel = el("div", { className: "panel" });
  const done = appliedThisWeek(), goal = weeklyGoal();
  const queue = STATE.jobs
    .filter(j => j.status === "active" && !j.closed)
    .sort((a, b) => b.focus - a.focus)
    .slice(0, queueSize());

  panel.append(
    el("h2", {}, "Today"),
    el("p", { className: "lede" },
      "The short queue, in focus order: the match score less what is already known to go " +
      "nowhere \u2014 ads that have aged past the point of a reply, and titles pitched above " +
      "your years. Every job says why it sits where it does."),
    el("div", { className: "goal" }, el("i", { style: `width:${Math.min(100, 100 * done / Math.max(1, goal))}%` })),
    el("p", { className: "hint" }, `${done} of ${goal} applications this week. Change the goal in Settings.`),
  );

  if (!queue.length) {
    panel.append(el("div", { className: "empty" }, "Nothing active. Run a search."));
    return panel;
  }
  queue.forEach(job => panel.append(jobCard(job)));
  return panel;
}

/* --------------------------------------------------------------------------
   Filtered out: what the settings are costing
-------------------------------------------------------------------------- */
function renderFiltered() {
  const panel = el("div", { className: "panel" });
  const entries = STATE.filtered || [];
  const tally = STATE.filtered_tally || { by_category: [], by_shape: [] };

  panel.append(
    el("h2", {}, "Filtered out"),
    el("p", { className: "lede" },
      "Nothing is thrown away. A filter one notch too strict is invisible while its victims " +
      "vanish, and \u201cthe board is empty\u201d looks exactly like \u201cthere were no jobs today\u201d. " +
      "These ads were rejected by your current settings \u2014 read them, and change the setting " +
      "or put one back."));

  if (!entries.length) {
    panel.append(el("div", { className: "empty" }, "Nothing has been filtered out yet."));
    return panel;
  }

  const total = (tally.by_category || []).reduce((sum, [, n]) => sum + n, 0) || entries.length;
  panel.append(el("div", { className: "tiles" },
    ...(tally.by_category || []).map(([name, n]) =>
      el("div", { className: "tile" },
        el("b", {}, String(n)),
        el("span", {}, `${name} \u00b7 ${Math.round(100 * n / total)}% of what was rejected`)))));

  const worst = (tally.by_category || [])[0];
  if (worst && worst[1] / total >= 0.4) {
    panel.append(el("p", { className: "lede" },
      el("b", {}, worst[0]), ` is rejecting ${Math.round(100 * worst[1] / total)}% of everything that gets this far. `,
      "If that is not what you meant, that is the setting to change \u2014 not the others."));
  }

  const shapes = tally.by_shape || [];
  if (shapes.length) {
    const top = shapes[0][1] || 1;
    panel.append(
      el("p", { className: "lede" }, "The commonest reasons, with the numbers blanked so they group:"),
      el("ul", { className: "bars" },
        ...shapes.map(([text, n]) => el("li", {},
          el("span", { className: "n" }, String(n)),
          el("span", { className: "track" }, el("i", { style: `width:${Math.round(100 * n / top)}%` })),
          el("span", {}, text)))));
  }

  const { near, far } = experienceSplit(entries);
  const shortTable = justShortTable(near);
  if (shortTable) panel.append(shortTable);
  const listed = entries.filter(entry => !near.includes(entry) && !far.includes(entry));
  if (far.length) {
    const one = far.length === 1;
    panel.append(el("p", { className: "hint" },
      `${far.length} ad${one ? " asks" : "s ask"} for well over your years and ` +
      `${one ? "is" : "are"} not listed one by one; they are counted above.`));
  }

  const rows = listed.map(entry => el("tr", {},
    el("td", {}, el("b", {}, entry.company || "\u2014")),
    el("td", {}, entry.title || "\u2014"),
    el("td", {}, entry.reason),
    el("td", {}, entry.source || ""),
    el("td", {},
      entry.url ? el("a", { href: entry.url, target: "_blank", rel: "noopener" }, "Open") : null,
      " ",
      button("Put back", () => putBack(entry)))));

  if (rows.length) {
    panel.append(el("h3", {}, "Everything else"), el("table", { className: "ftable" },
      el("thead", {}, el("tr", {},
        ...["Company", "Title", "Why it was rejected", "Source", ""].map(h => el("th", {}, h)))),
      el("tbody", {}, ...rows)));
  }
  return panel;
}

async function putBack(entry) {
  await api(`/api/filtered/${encodeURIComponent(entry.id)}/restore`, { method: "POST" });
  toast("Back on the board. The filter that rejected it is still on.");
  await refresh();
}

/* Ads set aside for years, split by how far off they are — recomputed from
   today's settings, so changing the margin shows at once. */
function experienceSplit(entries) {
  const held = STATE.experience && STATE.experience.held;
  const margin = (STATE.experience && STATE.experience.margin) || 0;
  const near = [], far = [];
  if (held == null) return { near, far };
  for (const entry of entries) {
    if (entry.category !== "experience" || entry.min_years == null) continue;
    const short = entry.min_years - held;
    if (short <= 0.001) continue;
    (short <= margin + 0.001 ? near : far).push(entry);
  }
  near.sort((a, b) => a.min_years - b.min_years);
  return { near, far };
}

function filteredSalary(entry) {
  if (!entry.salary_min) return "\u2014";
  const fmt = value => new Intl.NumberFormat(undefined, { style: "currency",
    currency: entry.salary_currency || "EUR", maximumFractionDigits: 0 }).format(value);
  const range = entry.salary_max && entry.salary_max !== entry.salary_min
    ? `${fmt(entry.salary_min)}\u2013${fmt(entry.salary_max)}` : fmt(entry.salary_min);
  return entry.salary_origin === "estimated" ? `${range} (est.)` : range;
}

function justShortTable(near) {
  if (!near.length) return null;
  const held = STATE.experience.held, margin = STATE.experience.margin;
  return el("div", {},
    el("h3", {}, `Just short on years (${near.length})`),
    el("p", { className: "lede" },
      `Your CV adds up to ${held} years and these ask for more, but within your margin of ` +
      `${margin} year${margin === 1 ? "" : "s"}. A form would filter you out; a direct email ` +
      "that names the gap often does not. Nothing here is deleted: raise your years or the " +
      "margin in Settings (or let time pass — the years come from your CV) and they return " +
      "to the board on their own."),
    el("table", { className: "ftable" },
      el("thead", {}, el("tr", {},
        ...["Company", "Title", "Asks for", "Short by", "Family", "Salary", ""].map(h => el("th", {}, h)))),
      el("tbody", {}, ...near.map(entry => el("tr", {},
        el("td", {}, el("b", {}, entry.company || "\u2014")),
        el("td", {}, entry.title || "\u2014"),
        el("td", {}, `${entry.min_years} years`),
        el("td", {}, `${Math.round((entry.min_years - held) * 10) / 10}`),
        el("td", {}, entry.family_label || ""),
        el("td", {}, filteredSalary(entry)),
        el("td", {},
          entry.url ? el("a", { href: entry.url, target: "_blank", rel: "noopener" }, "Open") : null,
          " ", button("Put back", () => putBack(entry))))))));
}
