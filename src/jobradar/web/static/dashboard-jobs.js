/* JobRadar dashboard — Adding jobs by hand, and deleting jobs.
   Plain scripts sharing one global scope, loaded in order by dashboard.html.

   "+ Job" is for ads no source finds: a referral, a newspaper, a company's own
   page. The text is read like any board's ad (family, requirements, years,
   things to ask), then the job is scored and lands on the board.

   Deleting is not discarding: a discarded job stays on the board with its
   status, a deleted one leaves it, and a later search will not bring the same
   ad back. Every deletion can be undone for a week. */

/* Ids ticked on the board, for deleting several at once. */
const SELECTED = new Set();

/* A toast with an action button, e.g. "Undo". */
function actionToast(message, label, action, ms = 9000) {
  const node = el("div", { className: "toast" }, message, " ");
  const act = el("button", { className: "ghost" }, label);
  act.onclick = async () => { node.remove(); try { await action(); } catch (e) { toast(e.message); } };
  node.append(act);
  document.body.append(node);
  setTimeout(() => node.remove(), ms);
}

async function deleteJobs(ids) {
  if (!ids.length) return;
  const result = await api("/api/jobs/delete", { method: "POST", body: JSON.stringify({ ids }) });
  ids.forEach(id => { SELECTED.delete(id); delete OUTPUTS[id]; });
  await refresh();
  actionToast(tn(result.deleted, "{n} job deleted.", "{n} jobs deleted."), t("Undo"), async () => {
    const back = await api("/api/jobs/undelete", { method: "POST", body: JSON.stringify({ ids }) });
    await refresh();
    toast(tn(back.restored, "{n} job back on the board.", "{n} jobs back on the board."));
  });
}

/* The checkbox in each card's corner. */
function selectBox(job) {
  const box = el("input", { type: "checkbox", className: "select-job", checked: SELECTED.has(job.id),
                            title: t("Select for deleting several at once") });
  box.setAttribute("aria-label", t("Select {title} at {company}",
                                   { title: job.title, company: job.company || t("unnamed company") }));
  box.onchange = () => { box.checked ? SELECTED.add(job.id) : SELECTED.delete(job.id); selectionBar(); };
  return box;
}

/* The bar above the board while jobs are ticked. */
function selectionBar() {
  let bar = $("#selection-bar");
  if (!bar) {
    bar = el("div", { id: "selection-bar", className: "selection-bar" });
    $("#toolbar").after(bar);
  }
  const visible = STATE ? STATE.jobs.filter(j => SELECTED.has(j.id)).map(j => j.id) : [];
  [...SELECTED].forEach(id => { if (!visible.includes(id)) SELECTED.delete(id); });
  bar.hidden = !SELECTED.size;
  bar.replaceChildren(
    el("b", {}, t("{n} selected", { n: SELECTED.size })),
    button(t("Delete them"), async () => deleteJobs([...SELECTED])),
    button(t("Clear the selection"), async () => {
      SELECTED.clear();
      document.querySelectorAll(".select-job").forEach(b => { b.checked = false; });
      selectionBar();
    }));
}

/* --------------------------------------------------------------------------
   + Job
-------------------------------------------------------------------------- */
function manualJobForm() {
  const families = (STATE.families || []).filter(f => f.enabled);
  const body = el("div", {},
    el("p", { className: "hint" },
      t("Paste the ad as it is. JobRadar reads it like any other: family, requirements, years asked for and anything worth asking about. Only the title is required.")),
    el("div", { className: "two" },
      el("div", {}, el("label", {}, t("Job title")), input("m_title", "")),
      el("div", {}, el("label", {}, t("Company")), input("m_company", ""))),
    el("div", { className: "two" },
      el("div", {}, el("label", {}, t("Link to the ad")), input("m_url", "", "https://…")),
      el("div", {}, el("label", {}, t("Location")), input("m_location", ""))),
    el("div", { className: "two" },
      el("div", {}, el("label", {}, t("Work mode")),
        selectFrom("m_mode", "unknown", [["unknown", t("Not stated")], ["remote", t("Remote")],
                                          ["hybrid", t("Hybrid")], ["onsite", t("On-site")]])),
      el("div", {}, el("label", {}, t("Job family")),
        selectFrom("m_family", "", [["", t("Let JobRadar decide")],
                                    ...families.map(f => [f.key, f.label])]))),
    el("label", {}, t("The ad's text")),
    el("textarea", { id: "m_description", rows: 8 }),
    el("div", { className: "two" },
      el("div", {}, el("label", {}, t("Published salary, from")),
        el("input", { id: "m_salmin", type: "number", min: "0", placeholder: t("blank = not published") })),
      el("div", {}, el("label", {}, t("to")),
        el("input", { id: "m_salmax", type: "number", min: "0" }))),
    el("div", { className: "two" },
      el("div", {}, el("label", {}, t("Where you are with it")),
        selectFrom("m_status", "active", [["active", t("Not applied yet")], ["applied", t("Applied")],
                                          ["discarded", t("Not interested")]])),
      el("div", {}, el("label", {}, t("Stage (if applied)")),
        selectFrom("m_stage", "", [["", "—"], ["applied", t("Applied")], ["screening", t("Screening")],
                                   ["interview", t("Interview")], ["offer", t("Offer")],
                                   ["rejected", t("Rejected")]]))),
    el("label", {}, t("Notes")),
    el("textarea", { id: "m_notes", rows: 2 }),
  );
  return body;
}

async function saveManualJob() {
  const value = id => ($("#" + id) ? $("#" + id).value.trim() : "");
  const payload = {
    title: value("m_title"), company: value("m_company"), url: value("m_url"),
    location: value("m_location"), work_mode: value("m_mode"), family: value("m_family"),
    description: value("m_description"),
    salary_min: value("m_salmin") ? Number(value("m_salmin")) : null,
    salary_max: value("m_salmax") ? Number(value("m_salmax")) : null,
    salary_currency: (STATE.settings.filters && STATE.settings.filters.salary_currency) || "EUR",
    status: value("m_status"), stage: value("m_stage") || null, notes: value("m_notes"),
  };
  if (!payload.title) { toast(t("The job title is required")); return; }
  const result = await api("/api/jobs", { method: "POST", body: JSON.stringify(payload) });
  $("#manual-job").close();
  TAB = payload.status === "applied" ? "applied" : payload.status === "discarded" ? "discarded" : "active";
  await refresh();
  const family = (STATE.families || []).find(f => f.key === result.family);
  toast(family ? t("Added as {family}.", { family: family.label }) : t("Added."));
}

function showManualJob() {
  let dialog = $("#manual-job");
  if (!dialog) {
    dialog = el("dialog", { id: "manual-job" },
      el("div", { className: "dialog-head" }, el("h2", { style: "margin:0" }, t("Add a job by hand"))),
      el("div", { className: "dialog-body", id: "manual-body" }),
      el("div", { className: "dialog-foot" },
        el("span", { className: "spacer" }),
        button(t("Cancel"), async () => dialog.close()),
        (() => { const b = button(t("Add it"), saveManualJob); b.className = "primary"; return b; })()));
    document.body.append(dialog);
  }
  $("#manual-body").replaceChildren(manualJobForm());
  dialog.showModal();
}
