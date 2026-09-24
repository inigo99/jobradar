/* JobRadar dashboard — Insights: is the search working?
   Plain scripts sharing one global scope, loaded in order by dashboard.html.

   The application funnel (response rates by source, job family and match
   score) and the run history (what each source fetched, kept and cost). The
   numbers come from /api/insights; see jobradar/insights.py for definitions. */

function rateText(group, minSample) {
  return group.response_rate == null ? `— (fewer than ${minSample})` : `${group.response_rate}%`;
}

function simpleTable(headers, rows) {
  return el("table", { className: "grid" },
    el("thead", {}, el("tr", {}, ...headers.map(h => el("th", {}, h)))),
    el("tbody", {}, ...rows.map(row => el("tr", {}, ...row.map(cell => el("td", {}, String(cell)))))));
}

function groupTable(title, groups, minSample) {
  const entries = Object.entries(groups || {});
  if (!entries.length) return null;
  return el("div", {},
    el("h3", {}, title),
    simpleTable(["", "Applications", "Human replies", "Next steps", "Rejections", "Response rate"],
      entries.map(([name, g]) =>
        [name, g.applications, g.replies, g.advances, g.rejections, rateText(g, minSample)])));
}

function renderInsights() {
  const panel = el("div", { className: "panel" }, el("h2", {}, "Insights"),
    el("p", { className: "hint" }, "Loading…"));
  api("/api/insights").then(({ funnel, history }) => {
    panel.innerHTML = "";
    const t = funnel.total;
    panel.append(
      el("h2", {}, "Is it working?"),
      el("p", { className: "hint" },
        "A reply is a person moving — a next step or a rejection, from your email or from the " +
        "stage you set. Automatic acknowledgements do not count. Rates need at least " +
        `${funnel.min_sample} applications in a group to mean anything.`),
      el("div", { className: "tiles" },
        ...[[t.applications, "applications"], [t.replies, "human replies"],
            [rateText(t, funnel.min_sample), "response rate"], [t.alive, "still alive"],
            [funnel.median_days_to_reply == null ? "—" : `${funnel.median_days_to_reply} d`,
             "median wait for a reply"]]
          .map(([value, label]) => el("div", { className: "tile" }, el("b", {}, String(value)),
                                      el("span", {}, label)))),
      groupTable("By source — which boards are worth it", funnel.by_source, funnel.min_sample),
      groupTable("By job family", funnel.by_family, funnel.min_sample),
      groupTable("By match score — does the score predict replies?", funnel.by_score,
                 funnel.min_sample),
    );
    if (funnel.saturated.length) {
      panel.append(el("h3", {}, "Companies with many ads or applications and no reply"),
        simpleTable(["Company", "On the board", "Applied", "Replies"],
          funnel.saturated.map(s => [s.company, s.on_board, s.applied, s.replies])));
    }
    if (funnel.waiting.length) {
      panel.append(el("h3", {}, "Waiting longest for a reply — worth a follow-up?"),
        simpleTable(["Company", "Job", "Applied on", "Days"],
          funnel.waiting.map(w => [w.company, w.title, w.applied_on, w.days])));
    }

    panel.append(el("h2", { style: "margin-top:26px" }, "Search runs"),
      el("p", { className: "hint" },
        history.runs
          ? `Last ${history.runs} runs since ${history.since}: ${history.fetched} fetched, ` +
            `${history.kept} kept, ${history.new} new` +
            (history.duplicate_share != null ? `, ${history.duplicate_share}% duplicates` : "") +
            (history.median_minutes != null ? `, median ${history.median_minutes} min a run` : "") + "."
          : "No search has run yet."));
    const sources = Object.entries(history.by_source);
    if (sources.length) {
      panel.append(el("h3", {}, "Per source"),
        simpleTable(["Source", "Runs", "Fetched", "Kept", "Kept %", "Failed", "Skipped"],
          sources.map(([name, s]) => [name, s.runs, s.fetched, s.kept,
                                      s.kept_share == null ? "—" : s.kept_share, s.failed, s.skipped])));
    }
    const filtered = Object.entries(history.filtered_by_category);
    if (filtered.length) {
      panel.append(el("p", { className: "hint" },
        "Filtered out over these runs: " + filtered.map(([c, n]) => `${n} by ${c}`).join(", ") + "."));
    }
    if (history.recent.length) {
      panel.append(el("h3", {}, "Recent runs"),
        simpleTable(["Started", "Minutes", "Fetched", "Kept", "New", "Problems"],
          history.recent.map(r => [r.started_at.replace("T", " "), r.minutes ?? "—", r.fetched,
                                   r.kept, r.new, r.errors])));
    }
  }).catch(error => {
    panel.innerHTML = "";
    panel.append(el("h2", {}, "Insights"), el("p", { className: "alert" }, error.message));
  });
  return panel;
}
