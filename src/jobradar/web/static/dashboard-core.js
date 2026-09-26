/* JobRadar dashboard — State, the API wrapper, formatting helpers and the job card.
   Plain scripts sharing one global scope, loaded in order by dashboard.html. */

/* ---------------------------------------------------------------------------
   State. One fetch of /api/state fills everything; every mutation refetches
   rather than patching the DOM by hand, which keeps the browser and the
   database from ever disagreeing about what is on screen.
--------------------------------------------------------------------------- */
let STATE = null;
let TAB = "today";
/* job id -> the card's output block (generated CV result, letter editor). */
const OUTPUTS = {};

const $ = (sel, root = document) => root.querySelector(sel);
const el = (tag, props = {}, ...children) => {
  const node = document.createElement(tag);
  for (const [name, value] of Object.entries(props)) {
    // data-* and aria-* are attributes, not DOM properties: assigning them
    // as properties leaves `dataset` empty.
    if (name.startsWith("data-") || name.startsWith("aria-")) {
      if (value != null) node.setAttribute(name, value);
    } else {
      node[name] = value;
    }
  }
  for (const child of children.flat()) {
    if (child == null) continue;
    node.append(child.nodeType ? child : document.createTextNode(child));
  }
  return node;
};

/* Like node.append(), but skips null and undefined — DOM append() would
   print them as the text "null". */
function appendAll(node, ...children) {
  node.append(...children.flat().filter(child => child != null));
  return node;
}

function toast(message, ms = 3200) {
  const node = el("div", { className: "toast", textContent: message });
  document.body.append(node);
  setTimeout(() => node.remove(), ms);
}

const localDateString = (date = new Date()) => {
  const offset = date.getTimezoneOffset() * 60000;
  return new Date(date.getTime() - offset).toISOString().slice(0, 10);
};

async function api(path, options = {}) {
  const headers = { "x-jobradar-language": LANG };
  if (options.body && !(options.body instanceof FormData)) headers["content-type"] = "application/json";
  const response = await fetch(path, { ...options, headers });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    // `detail` is a sentence for JobRadar's own errors, but a list for a
    // request the framework rejected before it reached JobRadar.
    let message = typeof payload.detail === "string" ? payload.detail
      : Array.isArray(payload.detail) ? payload.detail.map(e => e.msg).join("; ")
      : response.statusText || t("Request failed (HTTP {status})", { status: response.status });
    if (payload.hint) message += ` — ${payload.hint}`;
    throw new Error(message);
  }
  return payload;
}

async function refresh() {
  STATE = await api("/api/state");
  if (STATE.settings) chooseLanguage(STATE.settings.ui_language);
  render();
}

/* Values the server sends as codes, shown in the interface language. */
const workModeLabel = mode => ({ remote: t("remote"), hybrid: t("hybrid"), onsite: t("on-site"),
                                 unknown: t("work mode not stated") }[mode] || mode);
const stageLabel = stage => ({ applied: t("applied"), screening: t("screening"),
                               interview: t("interview"), offer: t("offer"),
                               rejected: t("rejected") }[stage] || stage);
const severityLabel = sev => ({ error: t("error"), warning: t("warning"), info: t("note") }[sev] || sev);
/* A country's name in the interface language, from the browser's own data;
   the server's English name when the browser has none. */
function countryName(code, fallback) {
  try {
    return new Intl.DisplayNames([LANG], { type: "region" }).of(code) || fallback;
  } catch (_) { return fallback; }
}

const difficultyLabel = level => ({ fast: t("fast"), medium: t("medium"), slow: t("slow") }[level] || level);

function money(job) {
  if (!job.salary_min) return t("salary not stated");
  const fmt = value => new Intl.NumberFormat(localeTag(), {
    style: "currency", currency: job.salary_currency || "EUR", maximumFractionDigits: 0,
  }).format(value);
  const range = job.salary_max && job.salary_max !== job.salary_min
    ? `${fmt(job.salary_min)}–${fmt(job.salary_max)}` : fmt(job.salary_min);
  return job.salary_origin === "estimated" ? t("{range} (estimated)", { range }) : range;
}

function jobCard(job) {
  const card = el("article", { className: "job" + (job.closed ? " closed" : "") });

  card.append(el("div", { className: "job-head" },
    selectBox(job),
    el("div", { style: "flex:1" },
      el("h3", {}, job.title),
      el("div", { className: "meta" },
        [job.company || t("unnamed company"), job.location, workModeLabel(job.work_mode),
         job.posted_at || t("no date"), money(job), job.family_label, job.source]
          .filter(Boolean).join(" · ")),
    ),
    el("div", { className: "score" },
      el("div", { className: "big" }, job.score_tailored ? job.score_tailored.toFixed(0) + "%" : "—"),
      el("div", { className: "delta" },
        job.score_base ? t("{base}% as-is · +{delta} tailored", { base: job.score_base.toFixed(0),
                                                                  delta: job.score_delta.toFixed(0) })
          : t("not scored")),
      job.focus ? el("div", { className: "focus" }, t("focus {n}", { n: job.focus.toFixed(0) })) : null,
    ),
  ));

  if (job.strengths.length || job.gaps.length) {
    /* Gaps carry how long they would take to close, so the list reads as a
       plan for the days before an interview instead of a list of failures.
       It never changes what goes on the CV: that still needs the skill to
       have actually been learnt. */
    const byKey = Object.fromEntries((job.gap_details || []).map(g => [g.label, g]));
    card.append(el("div", { className: "chips" },
      job.strengths.slice(0, 5).map(s => el("span", { className: "chip good" }, s)),
      job.gaps.slice(0, 4).map(g => {
        const detail = byKey[g];
        const chip = el("span", { className: "chip " + (detail ? detail.difficulty : "gap") },
                        detail ? t("gap: {skill} · {difficulty}", { skill: g, difficulty: difficultyLabel(detail.difficulty) })
                               : t("gap: {skill}", { skill: g }));
        if (detail) chip.title = detail.note;
        return chip;
      }),
    ));
  }
  const news = mailBlock(job);
  if (news) card.append(news);
  if (job.focus_reason) {
    card.append(el("div", { className: "why" }, t("Why it is here: {reason}.", { reason: job.focus_reason })));
  }
  for (const alert of job.alerts.slice(0, 3)) {
    card.append(el("div", { className: "alert" }, alert));
  }

  /* Actions. Applying is never automated: the button opens the ad. */
  const actions = el("div", { className: "job-actions" });
  actions.append(el("a", { href: job.url, target: "_blank", rel: "noopener" },
    el("button", { className: "primary" }, t("Open the ad"))));
  actions.append(button(t("Tailor CV"), () => buildCv(job, card)));
  actions.append(button(t("Cover letter"), () => buildDoc(job, "cover_letter", card)));
  actions.append(button(t("Application email"), () => buildDoc(job, "email", card)));
  actions.append(button(t("Form answers"), () => openAnswers(job, card)));
  if (job.has_cv) {
    actions.append(el("a", { href: `/api/jobs/${encodeURIComponent(job.id)}/cv/download` },
      el("button", {}, t("Download CV"))));
  }
  if (job.status !== "discarded") {
    actions.append(button(t("Not interested"), () => track(job, { status: "discarded" })));
  } else {
    actions.append(button(t("Restore"), () => track(job, { status: "active" })));
  }
  if (job.status !== "applied") {
    actions.append(button(t("Mark as applied"), () =>
      track(job, { status: "applied", stage: "applied", applied_on: localDateString() })));
  }
  const remove = button(t("Delete"), () => deleteJobs([job.id]));
  remove.className = "ghost danger";
  remove.title = t("Take it off the board; a later search will not bring it back (undo for a week)");
  actions.append(remove);
  card.append(actions);

  /* Tracking controls, only once the user has actually applied. */
  if (job.status === "applied") {
    const stage = el("select", {},
      ...["applied", "screening", "interview", "offer", "rejected"].map(value =>
        el("option", { value, selected: job.stage === value }, stageLabel(value))));
    stage.onchange = () => track(job, { status: "applied", stage: stage.value,
                                        applied_on: job.applied_on, notes: job.notes });
    const notes = el("input", { value: job.notes || "", placeholder: t("Notes (saved when you leave the field)") });
    notes.onchange = () => track(job, { status: "applied", stage: job.stage,
                                        applied_on: job.applied_on, notes: notes.value });
    card.append(el("div", { className: "track" },
      el("div", {}, el("label", {}, t("Stage")), stage),
      el("div", { style: "grid-column: span 2" }, el("label", {}, t("Notes")), notes),
    ));
  }

  const detail = el("details", { className: "detail" },
    el("summary", {}, t("What this job asks for")),
    el("div", { className: "detail-body" },
      el("div", { className: "chips" }, job.requirements.map(r => el("span", { className: "chip" }, r))),
      job.salary_basis ? el("p", { className: "hint" }, job.salary_basis) : null,
      job.min_years_experience ? el("p", { className: "hint" },
        t("Asks for {n}+ years of experience.", { n: job.min_years_experience })) : null,
    ));
  card.append(detail);

  // The same node across re-renders, so a generated CV or letter (and any
  // unsaved edit to it) survives refresh().
  const output = OUTPUTS[job.id] || (OUTPUTS[job.id] = el("div", { className: "job-output" }));
  card.append(output);
  return card;
}

function button(text, onclick) {
  const node = el("button", {}, text);
  node.onclick = async () => {
    node.disabled = true;
    const original = node.textContent;
    node.textContent = t("Working…");
    try { await onclick(); } catch (error) { toast(error.message); }
    node.textContent = original;
    node.disabled = false;
  };
  return node;
}

async function track(job, payload) {
  await api(`/api/jobs/${encodeURIComponent(job.id)}/application`, {
    method: "PUT",
    body: JSON.stringify({ status: "active", stage: null, applied_on: null, notes: "", ...payload }),
  });
  await refresh();
}

async function buildCv(job, card) {
  const result = await api(`/api/jobs/${encodeURIComponent(job.id)}/cv`, { method: "POST" });
  const output = $(".job-output", card);
  output.innerHTML = "";
  appendAll(output,
    el("h4", { style: "margin:14px 0 4px" }, t("Tailored CV")),
    el("p", { className: "hint" },
      t("{pages} page(s) · type scale {scale} · written by {by}",
        { pages: result.pages || "?", scale: result.scale,
          by: result.generated_by === "llm" ? t("the language model") : t("rules") })),
    el("div", { className: "doc-text" }, `${result.headline}\n\n${result.summary}`),
    lintBlock(result.lint),
    ...(result.warnings || []).map(w => el("div", { className: "alert" }, w)),
    ...(result.validation_notes || []).map(n =>
      el("div", { className: "alert" }, t("Draft rejected: {reason}", { reason: n }))),
  );
  await refresh();
}

/* Opens the saved letter or email when there is one — so a click never
   overwrites the user's edits — and writes it otherwise. */
async function buildDoc(job, kind, card) {
  const saved = await api(`/api/jobs/${encodeURIComponent(job.id)}/documents`);
  if (saved[kind]) { showDoc(job, kind, card, saved[kind]); return; }
  await writeDoc(job, kind, card);
}

async function writeDoc(job, kind, card) {
  const url = `/api/jobs/${encodeURIComponent(job.id)}/documents/${kind}`;
  const result = await api(url, { method: "POST" });
  showDoc(job, kind, card, result.document);
  await refresh();
}

/* The letter or email as an editable text box, with the review warnings.
   Edits are saved before the PDF is downloaded, so the PDF always matches
   what is on screen. */
function showDoc(job, kind, card, documentData) {
  const url = `/api/jobs/${encodeURIComponent(job.id)}/documents/${kind}`;
  const output = $(".job-output", card);
  const box = el("textarea", { className: "doc-text", rows: 14 });
  box.value = documentData.text;
  const warnings = el("div", {}, warningsBlock(documentData.warnings));
  const save = async () => {
    const saved = await api(url, { method: "PUT", body: JSON.stringify({ text: box.value }) });
    warnings.replaceChildren(...[warningsBlock(saved.document.warnings)].filter(Boolean));
    return saved.document;
  };
  output.innerHTML = "";
  appendAll(output,
    el("h4", { style: "margin:14px 0 4px" }, kind === "email" ? t("Application email") : t("Cover letter")),
    el("p", { className: "hint" },
      documentData.llm_generated ? t("Written by the language model. Edit it freely.") :
      t("Skeleton from your profile — the bracketed parts are yours to write.")),
    warnings,
    box,
    el("div", { className: "actions" },
      button(t("Save and check"), async () => { await save(); toast(t("Saved")); }),
      button(t("Copy"), async () => { await navigator.clipboard.writeText(box.value); toast(t("Copied")); }),
      button(t("Download PDF"), async () => { await save(); window.location.href = url + "/pdf"; }),
      button(t("Write it again"), async () => {
        if (confirm(t("Replace this text with a new draft? Your edits will be lost."))) {
          await writeDoc(job, kind, card);
        }
      })),
  );
}

function lintBlock(lint) {
  if (!lint) return null;
  const wrapper = el("details", { className: "detail", open: lint.findings.some(f => f.severity === "error") },
    el("summary", {}, t("Red-flag check: {summary}", { summary: lint.summary })));
  const body = el("div", { className: "detail-body" });
  for (const finding of lint.findings) {
    body.append(el("div", { className: "lint-finding" },
      el("span", { className: "sev " + finding.severity }, severityLabel(finding.severity) + " · "),
      el("span", {}, finding.message),
      finding.hint ? el("div", { className: "hint" }, finding.hint) : null));
  }
  if (!lint.findings.length) body.append(el("p", { className: "hint" }, t("Nothing flagged.")));
  wrapper.append(body);
  return wrapper;
}
