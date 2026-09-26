/* JobRadar dashboard — Insights: is the search working?
   Plain scripts sharing one global scope, loaded in order by dashboard.html.

   The application funnel (response rates by source, job family and match
   score) and the run history (what each source fetched, kept and cost). The
   numbers come from /api/insights; see jobradar/insights.py for definitions. */

function rateText(group, minSample) {
  return group.response_rate == null ? t("— (fewer than {n})", { n: minSample }) : `${group.response_rate}%`;
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
    simpleTable(["", t("Applications"), t("Human replies"), t("Next steps"), t("Rejections"), t("Response rate")],
      entries.map(([name, g]) =>
        [name, g.applications, g.replies, g.advances, g.rejections, rateText(g, minSample)])));
}

function renderInsights() {
  const panel = el("div", { className: "panel" }, el("h2", {}, t("Insights")),
    el("p", { className: "hint" }, t("Loading…")));
  api("/api/insights").then(({ funnel, history }) => {
    panel.innerHTML = "";
    const total = funnel.total;
    appendAll(panel,
      el("h2", {}, t("Is it working?")),
      el("p", { className: "hint" },
        t("A reply is a person moving — a next step or a rejection, from your email or from the stage you set. Automatic acknowledgements do not count. Rates need at least {n} applications in a group to mean anything.",
          { n: funnel.min_sample })),
      el("div", { className: "tiles" },
        ...[[total.applications, t("applications")], [total.replies, t("human replies")],
            [rateText(total, funnel.min_sample), t("response rate")], [total.alive, t("still alive")],
            [funnel.median_days_to_reply == null ? "—" : t("{n} d", { n: funnel.median_days_to_reply }),
             t("median wait for a reply")]]
          .map(([value, label]) => el("div", { className: "tile" }, el("b", {}, String(value)),
                                      el("span", {}, label)))),
      groupTable(t("By source — which boards are worth it"), funnel.by_source, funnel.min_sample),
      groupTable(t("By job family"), funnel.by_family, funnel.min_sample),
      groupTable(t("By match score — does the score predict replies?"), funnel.by_score,
                 funnel.min_sample),
    );
    if (funnel.saturated.length) {
      panel.append(el("h3", {}, t("Companies with many ads or applications and no reply")),
        simpleTable([t("Company"), t("On the board"), t("Applied"), t("Replies")],
          funnel.saturated.map(s => [s.company, s.on_board, s.applied, s.replies])));
    }
    if (funnel.waiting.length) {
      panel.append(el("h3", {}, t("Waiting longest for a reply — worth a follow-up?")),
        simpleTable([t("Company"), t("Job"), t("Applied on"), t("Days")],
          funnel.waiting.map(w => [w.company, w.title, w.applied_on, w.days])));
    }

    const parts = history.runs ? [
      t("Last {runs} runs since {since}: {fetched} fetched, {kept} kept, {new} new",
        { runs: history.runs, since: history.since, fetched: history.fetched, kept: history.kept,
          new: history.new }),
      history.duplicate_share != null ? t("{n}% duplicates", { n: history.duplicate_share }) : null,
      history.median_minutes != null ? t("median {n} min a run", { n: history.median_minutes }) : null,
    ].filter(Boolean) : [];
    panel.append(el("h2", { style: "margin-top:26px" }, t("Search runs")),
      el("p", { className: "hint" }, parts.length ? parts.join(", ") + "." : t("No search has run yet.")));
    const sources = Object.entries(history.by_source);
    if (sources.length) {
      panel.append(el("h3", {}, t("Per source")),
        simpleTable([t("Source"), t("Runs"), t("Fetched"), t("Kept"), t("Kept %"), t("Failed"), t("Skipped")],
          sources.map(([name, s]) => [name, s.runs, s.fetched, s.kept,
                                      s.kept_share == null ? "—" : s.kept_share, s.failed, s.skipped])));
    }
    const filtered = Object.entries(history.filtered_by_category);
    if (filtered.length) {
      panel.append(el("p", { className: "hint" },
        t("Filtered out over these runs: {list}.", {
          list: filtered.map(([c, n]) => t("{n} by {category}", { n, category: categoryLabel(c) })).join(", "),
        })));
    }
    if (history.recent.length) {
      panel.append(el("h3", {}, t("Recent runs")),
        simpleTable([t("Started"), t("Minutes"), t("Fetched"), t("Kept"), t("New"), t("Problems")],
          history.recent.map(r => [r.started_at.replace("T", " "), r.minutes ?? "—", r.fetched,
                                   r.kept, r.new, r.errors])));
    }
  }).catch(error => {
    panel.innerHTML = "";
    panel.append(el("h2", {}, t("Insights")), el("p", { className: "alert" }, error.message));
  });
  return panel;
}
