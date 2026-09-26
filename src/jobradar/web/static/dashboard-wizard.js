/* JobRadar dashboard — The first-run wizard.
   Plain scripts sharing one global scope, loaded in order by dashboard.html. */

/* --------------------------------------------------------------------------
   Onboarding wizard
-------------------------------------------------------------------------- */
const WIZARD = {
  step: 0,
  file: null,
  data: {
    full_name: "", email: "", country: "ES", default_language: "en", cv_text: "",
    titles: [], keywords: [], company_domains: [], enabled_sources: [], cv_template: "classic",
    filters: {
      work_modes: ["remote"], local_areas: [], home_country: "ES",
      allow_international_remote: true, eligible_countries: [],
      min_salary: null, salary_currency: "EUR", require_published_salary: false,
      max_years_experience: null, required_keywords: [], excluded_keywords: [],
      excluded_companies: [], max_age_days: 7, keep_undated: true,
    },
  },
};

const WIZARD_STEPS = () => [t("You"), t("Your CV"), t("What you're looking for"), t("Filters"),
                            t("Where to search")];

function wizardStep(step) {
  const data = WIZARD.data;
  const body = el("div");
  if (step === 0) {
    body.append(
      el("p", { className: "hint" },
        t("JobRadar keeps everything on this machine. Nothing here is uploaded anywhere.")),
      el("label", {}, t("Full name")),
      input("full_name", data.full_name, t("As it should appear on your CV")),
      el("div", { className: "two" },
        el("div", {}, el("label", {}, t("Email")), input("email", data.email, t("you@example.com"))),
        el("div", {}, el("label", {}, t("Country you work from")), countrySelect(data.country)),
      ),
      el("label", {}, t("Language for generated documents when the ad's language is unclear")),
      languageSelect(data.default_language),
    );
  } else if (step === 1) {
    body.append(
      el("p", { className: "hint" },
        t("Upload your current CV (PDF, DOCX or text) or paste it below. JobRadar reads it into a structured profile — that profile is then the only source of facts any generated document may use.")),
      el("label", {}, t("CV file")),
      el("input", { type: "file", id: "cv-file", accept: ".pdf,.docx,.txt,.md,.html" }),
      el("label", {}, t("…or paste the text")),
      el("textarea", { id: "cv-text", value: data.cv_text, placeholder: t("Paste your CV here") }),
      el("label", {}, t("CV template")),
      selectFrom("cv_template", data.cv_template,
        [["classic", t("Classic — serif, dense, conservative")],
         ["compact", t("Compact — sans-serif, tight")],
         ["modern", t("Modern — one accent colour, more space")]]),
      el("p", { className: "hint" },
        t("All three are single-column and machine-readable, which is what applicant tracking systems need. Your original layout is not reproduced pixel for pixel — its content is.")),
    );
  } else if (step === 2) {
    body.append(
      el("label", {}, t("Job titles you are looking for")),
      el("textarea", { id: "titles", value: data.titles.join("\n"),
                       placeholder: t("One per line, e.g.\nMachine Learning Engineer\nBackend Developer") }),
      el("p", { className: "hint" }, t("These are sent to every job board as search queries.")),
      el("label", {}, t("Extra keywords (optional)")),
      el("textarea", { id: "keywords", value: data.keywords.join("\n"),
                       placeholder: t("One per line, e.g.\nLLM\ncomputer vision") }),
    );
  } else if (step === 3) {
    const f = data.filters;
    body.append(
      el("label", {}, t("Acceptable ways of working")),
      el("div", { className: "row" },
        ...["remote", "hybrid", "onsite"].map(mode =>
          el("label", { className: "row", style: "margin:0 14px 0 0;font-weight:400" },
            el("input", { type: "checkbox", className: "mode", value: mode,
                          checked: f.work_modes.includes(mode) }), " " + workModeLabel(mode)))),
      el("label", {}, t("Places where you would also take a hybrid or on-site job")),
      input("local_areas", f.local_areas.join(", "), t("e.g. Navarre, Gipuzkoa, Berlin")),
      el("p", { className: "hint" },
        t("This is the exception to the rule above: remote anywhere, plus the office within reach.")),
      el("div", { className: "two" },
        el("div", {}, el("label", {}, t("Minimum salary per year (leave blank for none)")),
          el("input", { id: "min_salary", type: "number", value: f.min_salary ?? "", placeholder: "35000" })),
        el("div", {}, el("label", {}, t("Currency")), input("salary_currency", f.salary_currency, t("EUR"))),
      ),
      el("p", { className: "hint" },
        t("Most ads publish no salary, so JobRadar estimates one and marks it as an estimate. Nothing is dropped for an unknown salary unless you ask for published figures only.")),
      el("div", { className: "row", style: "margin-top:8px" },
        el("input", { type: "checkbox", id: "require_published", checked: f.require_published_salary }),
        el("label", { style: "margin:0" }, t("Only show jobs that publish a salary"))),
      el("div", { className: "two" },
        el("div", {}, el("label", {}, t("Skip ads asking for more than N years")),
          el("input", { id: "max_years", type: "number", value: f.max_years_experience ?? "", placeholder: "5" })),
        el("div", {}, el("label", {}, t("Only ads published in the last N days")),
          el("input", { id: "max_age", type: "number", value: f.max_age_days })),
      ),
      el("label", {}, t("Words that disqualify an ad")),
      input("excluded_keywords", f.excluded_keywords.join(", "), t("e.g. unpaid, commission only")),
      el("div", { className: "row", style: "margin-top:10px" },
        el("input", { type: "checkbox", id: "intl", checked: f.allow_international_remote }),
        el("label", { style: "margin:0" }, t("Include remote jobs from other countries when they allow it"))),
    );
  } else {
    body.append(
      el("p", { className: "hint" },
        t("Sources marked “restricted” read pages that were built for people, not programs. They are off unless you switch them on, and doing so is your decision under the site's terms and your own jurisdiction.")),
      el("div", { id: "sources" }, ...(STATE?.sources || []).map(sourceRow)),
      el("label", {}, t("Companies to watch")),
      el("textarea", { id: "domains", value: data.company_domains.join("\n"),
                       placeholder: t("One per line:\nstripe.com\ngreenhouse:airbnb\nlever:netflix") }),
      el("p", { className: "hint" },
        t("A bare domain is enough — JobRadar finds which hiring system the company uses and reads its job board directly.")),
    );
  }
  return body;
}

function sourceRow(source) {
  const enabled = WIZARD.data.enabled_sources.length
    ? WIZARD.data.enabled_sources.includes(source.id)
    : source.default_enabled;
  return el("div", { className: "source" },
    el("input", { type: "checkbox", className: "source-box", value: source.id, checked: enabled }),
    el("div", {},
      el("div", {}, el("b", {}, source.name), " ",
        el("span", { className: "tier " + source.tos_tier }, tierLabel(source.tos_tier))),
      source.required_env.length
        ? el("div", { className: "hint" }, t("Needs: {names} in your .env", { names: source.required_env.join(", ") }))
        : null,
      source.tos_note ? el("div", { className: "hint" }, source.tos_note) : null,
    ));
}

/* Source tiers as the server names them (sources/base.py). */
const tierLabel = tier => ({ open: t("open"), credentials: t("credentials"),
                             restricted: t("restricted") }[tier] || tier);

function input(id, value, placeholder = "") {
  return el("input", { id, value: value ?? "", placeholder });
}
function selectFrom(id, current, options) {
  return el("select", { id }, ...options.map(([value, text]) =>
    el("option", { value, selected: value === current }, text)));
}
function countrySelect(current) {
  const entries = Object.entries(STATE?.countries || { ES: "Spain" })
    .map(([code, name]) => [code, countryName(code, name)])
    .sort((a, b) => a[1].localeCompare(b[1], LANG));
  return selectFrom("country", current, entries);
}
function languageSelect(current) {
  return selectFrom("default_language", current,
    [["en", t("English")], ["es", t("Spanish")], ["fr", t("French")], ["de", t("German")],
     ["pt", t("Portuguese")], ["it", t("Italian")], ["nl", t("Dutch")]]);
}

function collectWizardStep(step) {
  const data = WIZARD.data;
  const value = id => ($("#" + id) ? $("#" + id).value.trim() : "");
  const list = id => value(id).split(/[\n,]/).map(s => s.trim()).filter(Boolean);
  if (step === 0) {
    data.full_name = value("full_name");
    data.email = value("email");
    data.country = value("country");
    data.default_language = value("default_language");
    data.filters.home_country = data.country;
    if (!data.full_name) return t("Your name is needed — it goes at the top of every CV.");
  } else if (step === 1) {
    const picker = $("#cv-file");
    WIZARD.file = picker && picker.files.length ? picker.files[0] : null;
    data.cv_text = value("cv-text");
    data.cv_template = value("cv_template");
  } else if (step === 2) {
    data.titles = list("titles");
    data.keywords = list("keywords");
    if (!data.titles.length) return t("Add at least one job title to search for.");
  } else if (step === 3) {
    const f = data.filters;
    f.work_modes = [...document.querySelectorAll(".mode:checked")].map(node => node.value);
    f.local_areas = list("local_areas");
    f.min_salary = value("min_salary") ? Number(value("min_salary")) : null;
    f.salary_currency = value("salary_currency") || "EUR";
    f.require_published_salary = $("#require_published").checked;
    f.max_years_experience = value("max_years") ? Number(value("max_years")) : null;
    f.max_age_days = Number(value("max_age") || 7);
    f.excluded_keywords = list("excluded_keywords");
    f.allow_international_remote = $("#intl").checked;
    if (!f.work_modes.length) return t("Pick at least one way of working.");
  } else {
    data.enabled_sources = [...document.querySelectorAll(".source-box:checked")].map(n => n.value);
    data.company_domains = list("domains");
  }
  return null;
}

function showWizard() {
  const dialog = $("#wizard");
  const paint = () => {
    $("#wizard-steps").innerHTML = "";
    const steps = WIZARD_STEPS();
    steps.forEach((title, index) => {
      const node = el("span", {}, title);
      node.setAttribute("aria-current", index === WIZARD.step);
      $("#wizard-steps").append(node, index < steps.length - 1 ? " › " : "");
    });
    $("#wizard-body").innerHTML = "";
    $("#wizard-body").append(wizardStep(WIZARD.step));
    $("#wizard-back").style.visibility = WIZARD.step ? "visible" : "hidden";
    $("#wizard-next").textContent = WIZARD.step === steps.length - 1 ? t("Finish") : t("Continue");
    $("#wizard-note").textContent = "";
  };
  $("#wizard-back").onclick = () => { collectWizardStep(WIZARD.step); WIZARD.step--; paint(); };
  $("#wizard-next").onclick = async () => {
    const problem = collectWizardStep(WIZARD.step);
    if (problem) { $("#wizard-note").textContent = problem; return; }
    if (WIZARD.step < WIZARD_STEPS().length - 1) { WIZARD.step++; paint(); return; }
    $("#wizard-next").disabled = true;
    $("#wizard-note").textContent = t("Reading your CV…");
    try {
      const form = new FormData();
      form.append("payload", JSON.stringify(WIZARD.data));
      if (WIZARD.file) form.append("cv_file", WIZARD.file);
      const result = await api("/api/onboarding", { method: "POST", body: form });
      dialog.close();
      await refresh();
      if (result.notes.length) alert(t("Setup done. Worth checking:") + "\n\n• " + result.notes.join("\n• "));
      toast(t("Ready. Press “Search now” to run the first search."));
    } catch (error) {
      $("#wizard-note").textContent = error.message;
    }
    $("#wizard-next").disabled = false;
  };
  paint();
  dialog.showModal();
}
