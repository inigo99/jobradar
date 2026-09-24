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
      el("label", {}, "CV PDF"),
      selectFrom("s_pdfengine", settings.cv_pdf_engine,
        [["auto", "Print the template with Chromium (built-in writer if it is missing)"],
         ["builtin", "Always the built-in writer (plainer, needs no browser)"]]),
      el("label", {}, "Phrases you never use (one per line)"),
      el("p", { className: "hint" },
        "Letters, emails and form answers that contain one are flagged, on top of the usual " +
        "template phrases (\"team player\", \"to whom it may concern\"…)."),
      el("textarea", { id: "s_banned", value: (settings.banned_phrases || []).join("\n") }),
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
    body.append(el("fieldset", {},
      el("legend", {}, "Your profile"),
      el("p", { className: "hint" },
        `${profile.full_name} · ${profile.years} years of experience · ` +
        `red-flag check ${profile.lint.score}/100`),
      lintBlock(profile.lint),
      el("label", {}, "Replace the profile with a new CV"),
      el("p", { className: "hint" },
        "Skills you added or deleted by hand, tuned ceilings and the CV per job family are kept."),
      el("input", { type: "file", id: "s_cv", accept: ".pdf,.docx,.txt,.md,.html" }),
    ), skillsFieldset(profile), variantsFieldset(profile));
  }
  return body;
}

/* --------------------------------------------------------------------------
   Your skills. Imported from the CV, then yours to add to, edit and delete.
   Evidence is how strongly the CV proves a skill today; the ceiling is how
   far a tailored CV may push it. A skill with no evidence can never be
   raised: that is what stops a generated document from inventing experience.
-------------------------------------------------------------------------- */
let DELETED_SKILLS = [];

function groupRow(group) {
  const row = el("div", { className: "group-row", "data-key": group.key || "" },
    el("input", { className: "g_label", value: group.label, placeholder: "Group, e.g. Tools" }),
    el("input", { className: "g_items", value: (group.items || []).join(", "),
                  placeholder: "Skills, comma separated" }));
  row.append(button("Remove", async () => row.remove()));
  return row;
}

function skillRow(skill) {
  const isNew = !skill.key;
  const row = el("div", { className: "skill-row", "data-key": skill.key || "" },
    isNew || skill.custom
      ? el("input", { className: "k_name", value: skill.label || "", placeholder: "Skill name" })
      : el("span", { className: "k_label" }, skill.label),
    el("input", { type: "number", step: "0.1", min: "0", max: "1", className: "ev",
                  value: skill.evidence, title: "Evidence: 1 shown in an achievement, 0.5 listed" }),
    el("input", { type: "number", step: "0.1", min: "0", max: "1", className: "ce",
                  value: skill.ceiling, title: "Ceiling: how far a tailored CV may push it" }),
    button("Delete", async () => {
      if (skill.key) DELETED_SKILLS.push(skill.key);
      row.remove();
    }));
  if (isNew || skill.custom) {
    row.append(el("input", { className: "k_aliases", value: (skill.aliases || []).join(", "),
                             placeholder: "Other names in ads (optional), comma separated" }));
  }
  return row;
}

function skillsFieldset(profile) {
  DELETED_SKILLS = [];
  const groups = el("div", { id: "s_groups" }, ...profile.skill_groups.map(groupRow));
  const table = el("div", { id: "s_skills" }, ...profile.skills.map(skillRow));
  return el("fieldset", {},
    el("legend", {}, "Your skills"),
    el("p", { className: "hint" },
      "Imported from your CV. Add, edit or delete them here; a skill you delete is not read " +
      "back from the CV on the next import."),
    el("label", {}, "Listed on your CV"),
    groups,
    button("Add a group", async () => groups.append(groupRow({ key: "", label: "", items: [] }))),
    el("label", {}, "Evidence and ceiling per skill"),
    el("p", { className: "hint" },
      "Evidence is how strongly your CV proves a skill today: 1 when an achievement shows it, " +
      "0.5 when it is only listed. The ceiling is how far a tailored CV may push it — how well " +
      "you could defend it in an interview. A skill with zero evidence can never be raised, " +
      "which is what stops any generated document from inventing experience. Typing a skill " +
      "into a group above is enough to add it; add it here to set its numbers or give it " +
      "other names."),
    el("div", { className: "skill-row skill-head" },
      el("b", {}, "Skill"), el("b", {}, "Evidence"), el("b", {}, "Ceiling"), el("span")),
    table,
    button("Add a skill", async () => table.append(skillRow({ key: "", label: "", evidence: 0.5,
                                                              ceiling: 0.9, aliases: [] }))),
  );
}

function collectSkills() {
  const list = text => text.split(",").map(s => s.trim()).filter(Boolean);
  const groups = [...document.querySelectorAll("#s_groups .group-row")]
    .map(row => ({ key: row.dataset.key, label: $(".g_label", row).value.trim(),
                   items: list($(".g_items", row).value) }))
    .filter(group => group.label && group.items.length);
  const skills = [...document.querySelectorAll("#s_skills .skill-row")].map(row => ({
    key: row.dataset.key,
    name: $(".k_name", row) ? $(".k_name", row).value.trim() : $(".k_label", row).textContent,
    evidence: Number($(".ev", row).value || 0),
    ceiling: Number($(".ce", row).value || 0),
    aliases: $(".k_aliases", row) ? list($(".k_aliases", row).value) : [],
  })).filter(skill => skill.key || skill.name);
  return { groups, skills, deleted: DELETED_SKILLS };
}

/* --------------------------------------------------------------------------
   CV per job family. A variant only selects and orders what the profile
   already holds (see CvVariant in jobradar/models.py): it can never add a
   fact. VARIANTS keeps every family's edits while the user switches between
   families; saveSettings() sends the whole set.
-------------------------------------------------------------------------- */
let VARIANTS = {};
const EMPTY_VARIANT = () => ({ headline: "", lead_bullets: [], hidden_bullets: [], skill_groups: [],
                               hidden_skill_groups: [], extra_skills: [] });

function choiceSelect(className, id, value, options) {
  const select = el("select", { className, "data-id": id },
    ...options.map(([v, text]) => el("option", { value: v }, text)));
  select.value = value;
  return select;
}

function variantForm(profile, family) {
  const variant = VARIANTS[family] || EMPTY_VARIANT();
  const bulletChoice = id => variant.lead_bullets.includes(id) ? "lead"
    : variant.hidden_bullets.includes(id) ? "hide" : "";
  const groupChoice = key => variant.skill_groups.includes(key) ? "lead"
    : variant.hidden_skill_groups.includes(key) ? "hide" : "";
  const choices = [["", "As ranked"], ["lead", "Put first"], ["hide", "Leave out"]];
  return el("div", { id: "s_variant", "data-family": family },
    el("label", {}, "Headline for this family"),
    el("input", { id: "s_v_headline", value: variant.headline,
                  placeholder: "empty = the ad's own title, e.g. \"Registered nurse\"" }),
    el("label", {}, "Achievements"),
    ...profile.experience.map(experience => el("div", {},
      el("div", { className: "hint" }, `${experience.title} — ${experience.organization}`),
      ...experience.bullets.map(bullet => el("div", { className: "variant-row" },
        choiceSelect("v_bullet", bullet.id, bulletChoice(bullet.id), choices),
        el("span", {}, bullet.text))))),
    el("label", {}, "Skill groups"),
    ...profile.skill_groups.map(group => el("div", { className: "variant-row" },
      choiceSelect("v_group", group.key, groupChoice(group.key), choices),
      el("span", {}, `${group.label}: ${group.items.join(", ")}`))),
    el("label", {}, "Extra skills to name under \"Also\" (at most four, comma separated)"),
    el("input", { id: "s_v_extra", value: variant.extra_skills.join(", "),
                  placeholder: "Only skills your profile proves are printed" }),
  );
}

/* Read the family shown on screen back into VARIANTS. */
function collectVariant() {
  const form = $("#s_variant");
  if (!form) return;
  const variant = EMPTY_VARIANT();
  variant.headline = $("#s_v_headline").value.trim();
  document.querySelectorAll("#s_variant .v_bullet").forEach(node => {
    if (node.value === "lead") variant.lead_bullets.push(node.dataset.id);
    if (node.value === "hide") variant.hidden_bullets.push(node.dataset.id);
  });
  document.querySelectorAll("#s_variant .v_group").forEach(node => {
    if (node.value === "lead") variant.skill_groups.push(node.dataset.id);
    if (node.value === "hide") variant.hidden_skill_groups.push(node.dataset.id);
  });
  variant.extra_skills = $("#s_v_extra").value.split(",").map(s => s.trim()).filter(Boolean).slice(0, 4);
  VARIANTS[form.dataset.family] = variant;
}

function variantsFieldset(profile) {
  VARIANTS = structuredClone(profile.family_variants || {});
  const families = STATE.families.filter(f => f.enabled);
  const start = families.find(f => VARIANTS[f.key]) || families[0];
  const holder = el("div", {}, variantForm(profile, start.key));
  const picker = selectFrom("s_v_family", start.key,
    families.map(f => [f.key, f.label + (VARIANTS[f.key] ? " ✓" : "")]));
  picker.addEventListener("change", () => {
    collectVariant();
    holder.replaceChildren(variantForm(profile, picker.value));
  });
  return el("fieldset", {},
    el("legend", {}, "CV per job family"),
    el("p", { className: "hint" },
      "Shape every CV sent to one family of jobs: a fixed headline, which achievements lead or " +
      "are left out, and which skill groups come first. This only selects and orders what your " +
      "profile already holds — it cannot add anything to it."),
    el("label", {}, "Family"), picker, holder);
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
  settings.cv_pdf_engine = value("s_pdfengine") || "auto";
  settings.banned_phrases = value("s_banned").split("\n").map(s => s.trim()).filter(Boolean);
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

  const saved = await api("/api/settings", { method: "PUT", body: JSON.stringify({ settings }) });

  if (STATE.profile) {
    await api("/api/profile/skills", { method: "PUT", body: JSON.stringify(collectSkills()) });
    collectVariant();
    await api("/api/profile", { method: "PUT", body: JSON.stringify({ family_variants: VARIANTS }) });
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
  toast(saved.restored
    ? `Settings saved. ${saved.restored} ad${saved.restored === 1 ? "" : "s"} set aside for years ` +
      "now within reach, back on the board."
    : "Settings saved");
}
