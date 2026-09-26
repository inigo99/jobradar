/* JobRadar dashboard — Filtering the board.
   Plain scripts sharing one global scope, loaded in order by dashboard.html.

   These filters only narrow what the board shows; they never reject a job.
   The search filters in Settings decide what reaches the board at all, and
   what they reject is kept under "Filtered out". The choices are remembered
   in this browser only. */

const BOARD_FILTERS = ["f_text", "f_mode", "f_where", "f_family", "f_source", "f_language",
                       "f_salary", "f_score"];
const FILTER_STORE = "jobradar.board-filters";
const languageName = code => ({ en: t("English"), es: t("Spanish"), fr: t("French"),
                                de: t("German"), pt: t("Portuguese"), it: t("Italian"),
                                nl: t("Dutch") }[code] || code.toUpperCase());

function salaryMidpoint(job) {
  if (!job.salary_min && !job.salary_max) return null;
  return ((job.salary_min || job.salary_max) + (job.salary_max || job.salary_min)) / 2;
}

function money0(value, currency) {
  return new Intl.NumberFormat(localeTag(), { style: "currency", currency: currency || "EUR",
                                            maximumFractionDigits: 0 }).format(value);
}

/* Keep a select's choice while its options follow the jobs on the board. */
function fillSelect(id, entries, allLabel) {
  const node = $("#" + id);
  const current = node.value;
  node.replaceChildren(el("option", { value: "" }, allLabel),
    ...entries.map(([value, label]) => el("option", { value }, label)));
  node.value = entries.some(([value]) => value === current) ? current : "";
}

/* Options and ranges come from the jobs actually on the board. */
function refreshFilterOptions() {
  const jobs = STATE.jobs;
  const count = key => {
    const seen = {};
    jobs.forEach(j => { if (j[key]) seen[j[key]] = (seen[j[key]] || 0) + 1; });
    return seen;
  };
  const families = {};
  jobs.forEach(j => { if (j.family) families[j.family] = j.family_label || j.family; });
  fillSelect("f_family", Object.entries(families).sort((a, b) => a[1].localeCompare(b[1])),
             t("All families"));
  fillSelect("f_source", Object.keys(count("source")).sort().map(s => [s, s]), t("All sources"));
  fillSelect("f_language", Object.keys(count("language")).sort()
    .map(code => [code, languageName(code)]), t("Any language"));

  const top = Math.max(0, ...jobs.map(j => salaryMidpoint(j) || 0));
  const slider = $("#f_salary");
  slider.max = String(Math.max(1000, Math.ceil(top / 1000) * 1000));
  if (Number(slider.value) > Number(slider.max)) slider.value = slider.max;
  showRangeValues();
}

function showRangeValues() {
  const currency = (STATE && STATE.settings.filters.salary_currency) || "EUR";
  const salary = Number($("#f_salary").value);
  $("#f_salary_value").textContent = salary ? t("from {value}", { value: money0(salary, currency) }) : t("any");
  const score = Number($("#f_score").value);
  $("#f_score_value").textContent = score ? t("from {value}", { value: `${score}%` }) : t("any");
}

/* Does a job pass the board filters? Unknown values never pass a filter
   that asks for a specific value, and never fail one left on "all". */
function passesBoardFilters(job) {
  const value = id => $("#" + id).value;
  const needle = value("f_text").trim().toLowerCase();
  if (needle && !`${job.title} ${job.company} ${job.location} ${job.family_label} ` +
      `${job.strengths.join(" ")} ${job.requirements.join(" ")}`.toLowerCase().includes(needle)) {
    return false;
  }
  if (value("f_mode") && job.work_mode !== value("f_mode")) return false;
  if (value("f_where") && job.where !== value("f_where")) return false;
  if (value("f_family") && job.family !== value("f_family")) return false;
  if (value("f_source") && job.source !== value("f_source")) return false;
  if (value("f_language") && job.language !== value("f_language")) return false;
  const salary = Number(value("f_salary"));
  if (salary && (salaryMidpoint(job) ?? -1) < salary) return false;
  const score = Number(value("f_score"));
  if (score && job.score_tailored < score) return false;
  return true;
}

function filtersActive() {
  return BOARD_FILTERS.some(id => {
    const node = $("#" + id);
    return node.type === "range" ? Number(node.value) > 0 : node.value.trim() !== "";
  });
}

function saveFilters() {
  const values = Object.fromEntries(BOARD_FILTERS.map(id => [id, $("#" + id).value]));
  try { localStorage.setItem(FILTER_STORE, JSON.stringify(values)); } catch (_) { /* private mode */ }
}

function restoreFilters() {
  let values = {};
  try { values = JSON.parse(localStorage.getItem(FILTER_STORE) || "{}"); } catch (_) { values = {}; }
  BOARD_FILTERS.forEach(id => {
    if (values[id] == null) return;
    const node = $("#" + id);
    if (node.tagName === "SELECT" && ![...node.options].some(o => o.value === values[id])) {
      // Options are filled from the jobs later; remember the choice until then.
      node.dataset.pending = values[id];
      return;
    }
    node.value = values[id];
  });
}

/* Selects whose options arrived after the saved choice was read. */
function applyPendingFilters() {
  BOARD_FILTERS.forEach(id => {
    const node = $("#" + id);
    if (node.dataset.pending && [...node.options].some(o => o.value === node.dataset.pending)) {
      node.value = node.dataset.pending;
    }
    delete node.dataset.pending;
  });
}

function clearFilters() {
  BOARD_FILTERS.forEach(id => {
    const node = $("#" + id);
    node.value = node.type === "range" ? "0" : "";
  });
  saveFilters();
  showRangeValues();
  render();
}

function wireFilters() {
  restoreFilters();
  BOARD_FILTERS.forEach(id => {
    $("#" + id).addEventListener("input", () => { showRangeValues(); saveFilters(); render(); });
  });
  $("#f_clear").onclick = clearFilters;
}
