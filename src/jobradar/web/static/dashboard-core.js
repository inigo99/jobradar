/* JobRadar dashboard — State, the API wrapper, formatting helpers and the job card.
   Plain scripts sharing one global scope, loaded in order by dashboard.html. */

/* ---------------------------------------------------------------------------
   State. One fetch of /api/state fills everything; every mutation refetches
   rather than patching the DOM by hand, which keeps the browser and the
   database from ever disagreeing about what is on screen.
--------------------------------------------------------------------------- */
let STATE = null;
let TAB = "today";

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
  const response = await fetch(path, {
    headers: options.body && !(options.body instanceof FormData)
      ? { "content-type": "application/json" } : undefined,
    ...options,
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    // `detail` is a sentence for JobRadar's own errors, but a list for a
    // request the framework rejected before it reached JobRadar.
    let message = typeof payload.detail === "string" ? payload.detail
      : Array.isArray(payload.detail) ? payload.detail.map(e => e.msg).join("; ")
      : response.statusText || `Request failed (HTTP ${response.status})`;
    if (payload.hint) message += ` — ${payload.hint}`;
    throw new Error(message);
  }
  return payload;
}

async function refresh() {
  STATE = await api("/api/state");
  render();
}

function money(job) {
  if (!job.salary_min) return "salary not stated";
  const fmt = value => new Intl.NumberFormat(undefined, {
    style: "currency", currency: job.salary_currency || "EUR", maximumFractionDigits: 0,
  }).format(value);
  const range = job.salary_max && job.salary_max !== job.salary_min
    ? `${fmt(job.salary_min)}–${fmt(job.salary_max)}` : fmt(job.salary_min);
  return job.salary_origin === "estimated" ? `${range} (estimated)` : range;
}

function jobCard(job) {
  const card = el("article", { className: "job" + (job.closed ? " closed" : "") });

  card.append(el("div", { className: "job-head" },
    el("div", { style: "flex:1" },
      el("h3", {}, job.title),
      el("div", { className: "meta" },
        [job.company || "unnamed company", job.location, job.work_mode,
         job.posted_at || "no date", money(job), job.family_label, job.source]
          .filter(Boolean).join(" · ")),
    ),
    el("div", { className: "score" },
      el("div", { className: "big" }, job.score_tailored ? job.score_tailored.toFixed(0) + "%" : "—"),
      el("div", { className: "delta" },
        job.score_base ? `${job.score_base.toFixed(0)}% as-is · +${job.score_delta.toFixed(0)} tailored` : "not scored"),
      job.focus ? el("div", { className: "focus" }, `focus ${job.focus.toFixed(0)}`) : null,
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
                        detail ? `gap: ${g} · ${detail.difficulty}` : "gap: " + g);
        if (detail) chip.title = detail.note;
        return chip;
      }),
    ));
  }
  if (job.focus_reason) {
    card.append(el("div", { className: "why" }, "Lower in the queue: " + job.focus_reason + "."));
  }
  for (const alert of job.alerts.slice(0, 3)) {
    card.append(el("div", { className: "alert" }, alert));
  }

  /* Actions. Applying is never automated: the button opens the ad. */
  const actions = el("div", { className: "job-actions" });
  actions.append(el("a", { href: job.url, target: "_blank", rel: "noopener" },
    el("button", { className: "primary" }, "Open the ad")));
  actions.append(button("Tailor CV", () => buildCv(job, card)));
  actions.append(button("Cover letter", () => buildDoc(job, "cover_letter", card)));
  actions.append(button("Application email", () => buildDoc(job, "email", card)));
  if (job.has_cv) {
    actions.append(el("a", { href: `/api/jobs/${encodeURIComponent(job.id)}/cv/download` },
      el("button", {}, "Download CV")));
  }
  if (job.status !== "discarded") {
    actions.append(button("Not interested", () => track(job, { status: "discarded" })));
  } else {
    actions.append(button("Restore", () => track(job, { status: "active" })));
  }
  if (job.status !== "applied") {
    actions.append(button("Mark as applied", () =>
      track(job, { status: "applied", stage: "applied", applied_on: localDateString() })));
  }
  card.append(actions);

  /* Tracking controls, only once the user has actually applied. */
  if (job.status === "applied") {
    const stage = el("select", {},
      ...["applied", "screening", "interview", "offer", "rejected"].map(value =>
        el("option", { value, selected: job.stage === value }, value)));
    stage.onchange = () => track(job, { status: "applied", stage: stage.value,
                                        applied_on: job.applied_on, notes: job.notes });
    const notes = el("input", { value: job.notes || "", placeholder: "Notes (saved when you leave the field)" });
    notes.onchange = () => track(job, { status: "applied", stage: job.stage,
                                        applied_on: job.applied_on, notes: notes.value });
    card.append(el("div", { className: "track" },
      el("div", {}, el("label", {}, "Stage"), stage),
      el("div", { style: "grid-column: span 2" }, el("label", {}, "Notes"), notes),
    ));
  }

  const detail = el("details", { className: "detail" },
    el("summary", {}, "What this job asks for"),
    el("div", { className: "detail-body" },
      el("div", { className: "chips" }, job.requirements.map(r => el("span", { className: "chip" }, r))),
      job.salary_basis ? el("p", { className: "hint" }, job.salary_basis) : null,
      job.min_years_experience ? el("p", { className: "hint" },
        `Asks for ${job.min_years_experience}+ years of experience.`) : null,
    ));
  card.append(detail);

  const output = el("div", { className: "job-output" });
  card.append(output);
  return card;
}

function button(text, onclick) {
  const node = el("button", {}, text);
  node.onclick = async () => {
    node.disabled = true;
    const original = node.textContent;
    node.textContent = "Working…";
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
  output.append(
    el("h4", { style: "margin:14px 0 4px" }, "Tailored CV"),
    el("p", { className: "hint" },
      `${result.pages || "?"} page(s) · type scale ${result.scale} · written by ${result.generated_by}`),
    el("div", { className: "doc-text" }, `${result.headline}\n\n${result.summary}`),
    lintBlock(result.lint),
    ...(result.warnings || []).map(w => el("div", { className: "alert" }, w)),
    ...(result.validation_notes || []).map(n =>
      el("div", { className: "alert" }, "Draft rejected: " + n)),
  );
  await refresh();
}

async function buildDoc(job, kind, card) {
  const result = await api(`/api/jobs/${encodeURIComponent(job.id)}/documents/${kind}`, { method: "POST" });
  const output = $(".job-output", card);
  const text = result.document.text;
  output.innerHTML = "";
  output.append(
    el("h4", { style: "margin:14px 0 4px" }, kind === "email" ? "Application email" : "Cover letter"),
    el("p", { className: "hint" },
      result.document.llm_generated ? "Written by the language model." :
      "Skeleton from your profile — the bracketed parts are yours to write."),
    el("div", { className: "doc-text" }, text),
    button("Copy", async () => { await navigator.clipboard.writeText(text); toast("Copied"); }),
  );
  await refresh();
}

function lintBlock(lint) {
  if (!lint) return null;
  const wrapper = el("details", { className: "detail", open: lint.findings.some(f => f.severity === "error") },
    el("summary", {}, `Red-flag check: ${lint.summary}`));
  const body = el("div", { className: "detail-body" });
  for (const finding of lint.findings) {
    body.append(el("div", { className: "lint-finding" },
      el("span", { className: "sev " + finding.severity }, finding.severity + " · "),
      el("span", {}, finding.message),
      finding.hint ? el("div", { className: "hint" }, finding.hint) : null));
  }
  if (!lint.findings.length) body.append(el("p", { className: "hint" }, "Nothing flagged."));
  wrapper.append(body);
  return wrapper;
}
