/* JobRadar dashboard — The Settings dialog.
   Plain scripts sharing one global scope, loaded in order by dashboard.html. */

/* --------------------------------------------------------------------------
   Settings
-------------------------------------------------------------------------- */
function settingsBody() {
  const settings = STATE.settings;
  const f = settings.filters;
  const body = el("div");
  const profile = STATE.profile;

  body.append(
    el("fieldset", {},
      el("legend", {}, "You"),
      el("div", { className: "two" },
        el("div", {}, el("label", {}, "Full name"), input("s_name", settings.full_name)),
        el("div", {}, el("label", {}, "Email"), input("s_email", settings.email)),
      ),
      el("div", { className: "two" },
        el("div", {}, el("label", {}, "Country"), countrySelectFor("s_country", settings.country)),
        el("div", {}, el("label", {}, "Document language fallback"),
          selectFrom("s_language", settings.default_language,
            [["en","English"],["es","Spanish"],["fr","French"],["de","German"],["pt","Portuguese"],["it","Italian"]])),
      ),
      el("label", {}, "CV template"),
      selectFrom("s_template", settings.cv_template,
        [["classic","Classic"],["compact","Compact"],["modern","Modern"]]),
    ),

    el("fieldset", {},
      el("legend", {}, "What you're looking for"),
      el("label", {}, "Job titles"),
      el("textarea", { id: "s_titles", value: settings.search.titles.join("\n") }),
      el("label", {}, "Extra keywords"),
      el("textarea", { id: "s_keywords", value: settings.search.keywords.join("\n") }),
    ),

    el("fieldset", {},
      el("legend", {}, "Filters"),
      el("label", {}, "Acceptable ways of working"),
      el("div", { className: "row" },
        ...["remote", "hybrid", "onsite"].map(mode =>
          el("label", { className: "row", style: "margin:0 14px 0 0;font-weight:400" },
            el("input", { type: "checkbox", className: "s_mode", value: mode,
                          checked: f.work_modes.includes(mode) }), " " + mode))),
      el("label", {}, "Areas where hybrid or on-site is fine"),
      input("s_areas", f.local_areas.join(", ")),
      el("div", { className: "two" },
        el("div", {}, el("label", {}, "Minimum salary"),
          el("input", { id: "s_minsal", type: "number", value: f.min_salary ?? "" })),
        el("div", {}, el("label", {}, "Currency"), input("s_currency", f.salary_currency)),
      ),
      el("div", { className: "two" },
        el("div", {}, el("label", {}, "Max years of experience asked for"),
          el("input", { id: "s_maxyears", type: "number", value: f.max_years_experience ?? "",
                        placeholder: profile ? `empty = from your CV (${profile.years})` : "empty = from your CV" })),
        el("div", {}, el("label", {}, "Ads from the last N days"),
          el("input", { id: "s_age", type: "number", value: f.max_age_days })),
      ),
      el("div", { className: "row", style: "margin-top:6px" },
        el("input", { type: "checkbox", id: "s_profileyears", checked: f.use_profile_years }),
        el("label", { style: "margin:0" }, "Take the ceiling from my CV's own dates, so it rises on its own")),
      el("div", { className: "two" },
        el("div", {}, el("label", {}, "Years margin — how far past mine still counts as \u201cjust short\u201d"),
          el("input", { id: "s_yearsmargin", type: "number", step: "0.5", value: f.years_margin })),
        el("div", {}, el("label", {}, "Applications a week you are aiming for"),
          el("input", { id: "s_goal", type: "number", value: settings.weekly_goal })),
      ),
      el("p", { className: "hint" },
        "An ad that states no minimum is never filtered on years \u2014 most state none. " +
        "Everything rejected here is kept under \u201cFiltered out\u201d, with the ones you " +
        "miss by a hair separated from the ones far out of reach."),
      el("label", {}, "Excluded keywords"), input("s_exclude", f.excluded_keywords.join(", ")),
      el("label", {}, "Excluded companies"), input("s_excludeco", f.excluded_companies.join(", ")),
      el("div", { className: "row", style: "margin-top:10px" },
        el("input", { type: "checkbox", id: "s_intl", checked: f.allow_international_remote }),
        el("label", { style: "margin:0" }, "Include international remote when the ad allows it")),
      el("div", { className: "row", style: "margin-top:6px" },
        el("input", { type: "checkbox", id: "s_published", checked: f.require_published_salary }),
        el("label", { style: "margin:0" }, "Published salaries only")),
    ),

    el("fieldset", {},
      el("legend", {}, "Where to search"),
      ...STATE.sources.map(source => {
        const enabled = settings.sources.enabled.length
          ? settings.sources.enabled.includes(source.id) : source.default_enabled;
        return el("div", { className: "source" },
          el("input", { type: "checkbox", className: "s_source", value: source.id, checked: enabled }),
          el("div", { style: "flex:1" },
            el("div", {}, el("b", {}, source.name), " ",
              el("span", { className: "tier " + source.tos_tier }, source.tos_tier)),
            source.required_env.length
              ? el("div", { className: "hint" }, "Needs " + source.required_env.join(", ")) : null,
            source.tos_note ? el("div", { className: "hint" }, source.tos_note) : null),
          el("label", { className: "row", style: "margin:0;font-weight:400;white-space:nowrap" },
            el("input", { type: "checkbox", className: "s_weekly", value: source.id,
                          checked: settings.sources.weekly.includes(source.id) }), " weekly"));
      }),
      el("div", { className: "two" },
        el("div", {}, el("label", {}, "Weekly sources run on"),
          selectFrom("s_weeklyday", String(settings.sources.weekly_day),
            ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
              .map((day, index) => [String(index), day]))),
        el("p", { className: "hint", style: "align-self:end" },
          "A weekly source is only searched on that day: worth it for boards whose ads stay " +
          "up for weeks and rarely change."),
      ),
      el("label", {}, "Companies to watch"),
      el("textarea", { id: "s_domains", value: settings.sources.company_domains.join("\n") }),
      el("div", { className: "two" },
        el("div", {}, el("label", {}, "Seconds between requests"),
          el("input", { id: "s_delay", type: "number", step: "0.5", value: settings.sources.request_delay })),
        el("div", {}, el("label", {}, "Results per source per run"),
          el("input", { id: "s_limit", type: "number", value: settings.sources.max_results_per_source })),
      ),
    ),

    familiesFieldset(),

    el("fieldset", {},
      el("legend", {}, "Replies in your email"),
      el("p", { className: "hint" },
        STATE.mail_configured
          ? "Your mail server is configured. JobRadar reads it without changing anything: " +
            "nothing is marked as read, moved or answered."
          : "Set JOBRADAR_IMAP_HOST, JOBRADAR_IMAP_USER and JOBRADAR_IMAP_PASSWORD (an app " +
            "password) in your .env file first; see .env.example."),
      el("div", { className: "row", style: "margin-top:6px" },
        el("input", { type: "checkbox", id: "s_mail", checked: settings.mail.enabled }),
        el("label", { style: "margin:0" },
          "Read replies to my applications (rejections, next steps, interview times)")),
      el("div", { className: "row", style: "margin-top:6px" },
        el("input", { type: "checkbox", id: "s_mailsearch", checked: settings.mail.check_after_search }),
        el("label", { style: "margin:0" }, "Also check after every search")),
      el("label", {}, "First check looks back this many days"),
      el("input", { id: "s_maildays", type: "number", min: "1", max: "365", value: settings.mail.days_back }),
    ),

    el("fieldset", {},
      el("legend", {}, "Language model (optional)"),
      el("p", { className: "hint" },
        "Everything works without one. A model reads each ad properly and writes the summary " +
        "and letters; keys are read from your .env file and never stored in the database."),
      el("div", { className: "two" },
        el("div", {}, el("label", {}, "Provider"),
          selectFrom("s_provider", settings.llm.provider,
            [["none","None — rules only"],["anthropic","Anthropic"],["openai","OpenAI"],
             ["gemini","Google Gemini (GEMINI_API_KEY)"],
             ["openai-compatible","OpenAI-compatible endpoint"],["ollama","Ollama (local)"]])),
        el("div", {}, el("label", {}, "Model"),
          input("s_model", settings.llm.model, "blank = provider default, e.g. gemini-3.5-flash")),
      ),
      el("div", { className: "two" },
        el("div", {}, el("label", {}, "Base URL (compatible endpoints only)"),
          input("s_baseurl", settings.llm.base_url)),
        el("div", {}, el("label", {}, "Max model calls per run"),
          el("input", { id: "s_calls", type: "number", value: settings.llm.max_calls_per_run })),
      ),
    ),
  );

  if (profile) {
    const skills = el("div");
    for (const skill of profile.skills.slice(0, 40)) {
      skills.append(el("div", { className: "skill-row" },
        el("span", {}, skill.label),
        el("input", { type: "number", step: "0.1", min: "0", max: "1",
                      className: "ev", "data-key": skill.key, value: skill.evidence }),
        el("input", { type: "number", step: "0.1", min: "0", max: "1",
                      className: "ce", "data-key": skill.key, value: skill.ceiling })));
    }
    body.append(el("fieldset", {},
      el("legend", {}, "Your profile"),
      el("p", { className: "hint" },
        `${profile.full_name} · ${profile.years} years of experience · ` +
        `red-flag check ${profile.lint.score}/100`),
      lintBlock(profile.lint),
      el("label", {}, "Replace the profile with a new CV"),
      el("input", { type: "file", id: "s_cv", accept: ".pdf,.docx,.txt,.md,.html" }),
      el("label", {}, "Evidence and ceiling per skill"),
      el("p", { className: "hint" },
        "Evidence is how strongly your CV proves a skill today. Ceiling is how far a tailored CV " +
        "may push it — that is, how well you could defend it in an interview. A skill with zero " +
        "evidence can never be raised, which is what stops any generated document from inventing " +
        "experience."),
      el("div", { className: "skill-row" },
        el("b", {}, "Skill"), el("b", {}, "Evidence"), el("b", {}, "Ceiling")),
      skills,
    ));
  }
  return body;
}

/* --------------------------------------------------------------------------
   Job families. The catalogue lives in resources/families.yaml; only what the
   user changes is stored (Settings.families), so catalogue improvements still
   reach every family left alone.
-------------------------------------------------------------------------- */
function familyRow(family) {
  const row = el("div", { className: "family-row", "data-key": family.key,
                          "data-custom": family.custom ? "1" : "" },
    el("input", { type: "checkbox", className: "f_enabled", checked: family.enabled,
                  disabled: family.key === "general", title: "Use this family" }),
    el("input", { className: "f_label", value: family.label, placeholder: "Name" }),
    el("input", { type: "number", className: "f_priority", step: "0.05", min: "0", max: "3",
                  value: family.priority, title: "Priority: 1 neutral, above favours, below demotes" }),
    el("input", { className: "f_keywords", value: family.keywords.join(", "),
                  placeholder: "Title keywords, comma separated; end with * for a prefix" }),
  );
  if (family.custom) {
    row.append(button("Remove", () => row.remove()));
  }
  return row;
}

function familiesFieldset() {
  const rows = el("div", { id: "s_families" }, ...STATE.families.map(familyRow));
  return el("fieldset", {},
    el("legend", {}, "Job families"),
    el("p", { className: "hint" },
      "Every job is sorted into a family by the words in its title. A priority above 1 moves " +
      "that family up the board, below 1 moves it down; it never changes the match score. " +
      "Families also set the starting salary band for ads that publish none."),
    el("div", { className: "family-row family-head" },
      el("b", {}, "On"), el("b", {}, "Family"), el("b", {}, "Priority"), el("b", {}, "Keywords")),
    rows,
    button("Add a family", () => rows.append(familyRow({
      key: "custom_" + Date.now().toString(36), label: "", keywords: [], priority: 1,
      enabled: true, custom: true,
    }))),
  );
}

/* Only the differences from the catalogue are stored, so a family the user
   left alone keeps receiving catalogue updates. */
function collectFamilies() {
  const byKey = Object.fromEntries(STATE.families.map(f => [f.key, f]));
  const overrides = {};
  document.querySelectorAll("#s_families .family-row").forEach(row => {
    const key = row.dataset.key;
    const label = $(".f_label", row).value.trim();
    const keywords = $(".f_keywords", row).value.split(",").map(k => k.trim()).filter(Boolean);
    const priority = Number($(".f_priority", row).value || 1);
    const enabled = $(".f_enabled", row).checked;
    if (row.dataset.custom) {
      if (label) overrides[key] = { label, keywords, priority, enabled };
      return;
    }
    const base = (byKey[key] || {}).default || {};
    const change = {};
    if (label && label !== base.label) change.label = label;
    if (keywords.join("|") !== (base.keywords || []).join("|")) change.keywords = keywords;
    if (priority !== 1) change.priority = priority;
    if (!enabled) change.enabled = false;
    if (Object.keys(change).length) overrides[key] = change;
  });
  return overrides;
}

function countrySelectFor(id, current) {
  const entries = Object.entries(STATE.countries).sort((a, b) => a[1].localeCompare(b[1]));
  return selectFrom(id, current, entries);
}

async function saveSettings() {
  const settings = structuredClone(STATE.settings);
  const value = id => ($("#" + id) ? $("#" + id).value.trim() : "");
  const list = id => value(id).split(/[\n,]/).map(s => s.trim()).filter(Boolean);

  settings.full_name = value("s_name");
  settings.email = value("s_email");
  settings.country = value("s_country");
  settings.default_language = value("s_language");
  settings.cv_template = value("s_template");
  settings.search.titles = list("s_titles");
  settings.search.keywords = list("s_keywords");

  const f = settings.filters;
  f.work_modes = [...document.querySelectorAll(".s_mode:checked")].map(n => n.value);
  f.local_areas = list("s_areas");
  f.min_salary = value("s_minsal") ? Number(value("s_minsal")) : null;
  f.salary_currency = value("s_currency") || "EUR";
  f.max_years_experience = value("s_maxyears") ? Number(value("s_maxyears")) : null;
  f.use_profile_years = $("#s_profileyears").checked;
  f.years_margin = Number(value("s_yearsmargin") || 1);
  settings.weekly_goal = Number(value("s_goal") || 10);
  f.max_age_days = Number(value("s_age") || 7);
  f.excluded_keywords = list("s_exclude");
  f.excluded_companies = list("s_excludeco");
  f.allow_international_remote = $("#s_intl").checked;
  f.require_published_salary = $("#s_published").checked;

  settings.sources.enabled = [...document.querySelectorAll(".s_source:checked")].map(n => n.value);
  settings.sources.disabled = [...document.querySelectorAll(".s_source:not(:checked)")].map(n => n.value);
  settings.sources.company_domains = list("s_domains");
  settings.sources.weekly = [...document.querySelectorAll(".s_weekly:checked")].map(n => n.value);
  settings.sources.weekly_day = Number(value("s_weeklyday") || 0);
  settings.families = collectFamilies();
  settings.mail.enabled = $("#s_mail").checked;
  settings.mail.check_after_search = $("#s_mailsearch").checked;
  settings.mail.days_back = Number(value("s_maildays") || 30);
  settings.sources.request_delay = Number(value("s_delay") || 1);
  settings.sources.max_results_per_source = Number(value("s_limit") || 100);

  settings.llm.provider = value("s_provider");
  settings.llm.model = value("s_model");
  settings.llm.base_url = value("s_baseurl");
  settings.llm.max_calls_per_run = Number(value("s_calls") || 60);

  await api("/api/settings", { method: "PUT", body: JSON.stringify({ settings }) });

  const evidence = {}, ceiling = {};
  document.querySelectorAll(".ev").forEach(n => evidence[n.dataset.key] = Number(n.value));
  document.querySelectorAll(".ce").forEach(n => ceiling[n.dataset.key] = Number(n.value));
  if (Object.keys(evidence).length) {
    await api("/api/profile", { method: "PUT", body: JSON.stringify({ evidence, ceiling }) });
  }
  const picker = $("#s_cv");
  if (picker && picker.files.length) {
    const form = new FormData();
    form.append("cv_file", picker.files[0]);
    const result = await api("/api/profile/reimport", { method: "POST", body: form });
    if (result.notes.length) alert("New CV imported. Worth checking:\n\n• " + result.notes.join("\n• "));
  }
  $("#settings").close();
  await refresh();
  toast("Settings saved");
}
