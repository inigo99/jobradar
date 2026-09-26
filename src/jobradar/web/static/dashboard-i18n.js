/* JobRadar dashboard — The interface language. Loaded first.
   Plain scripts sharing one global scope, loaded in order by dashboard.html.

   Every piece of interface text is written in English and passed through
   t(): t("Search now"), or with values, t("{n} of {total} shown", { n, total }).
   The English sentence is the key; dashboard-i18n-es.js holds the Spanish
   one for each. tests/test_i18n.py fails when a t("…") has no translation,
   so the catalogue cannot silently fall behind.

   Text produced by the server (alerts, reasons, findings, errors) is
   translated there: api() sends the chosen language with every request. What
   the user wrote — their CV, notes, letters — is never translated. */

const I18N = {};              // language code -> { "English text": "translation" }
let LANG = "en";

/* The language to show: the saved choice, else the browser's, else English. */
function chooseLanguage(saved) {
  const wanted = saved && saved !== "auto" ? saved
    : String((navigator.languages && navigator.languages[0]) || navigator.language || "en");
  const code = wanted.slice(0, 2).toLowerCase();
  LANG = I18N[code] || code === "en" ? code : "en";
  document.documentElement.lang = LANG;
  translateStatic();
}

function t(text, values) {
  let out = (I18N[LANG] && I18N[LANG][text]) || text;
  if (values) {
    out = out.replace(/\{(\w+)\}/g, (whole, name) => (name in values ? String(values[name]) : whole));
  }
  return out;
}

/* Singular or plural: t(one) when n is 1, t(many) otherwise, with {n} filled in. */
function tn(n, one, many, values = {}) {
  return t(n === 1 ? one : many, { n, ...values });
}

/* The page's own HTML marks its text with data-i18n (text), data-i18n-placeholder,
   data-i18n-title and data-i18n-aria-label; the English stays in the markup
   and is remembered, so switching language back and forth works. */
function translateStatic(root = document) {
  root.querySelectorAll("[data-i18n]").forEach(node => {
    node.dataset.i18nSource = node.dataset.i18nSource || node.textContent.trim();
    node.textContent = t(node.dataset.i18nSource);
  });
  for (const attribute of ["placeholder", "title", "aria-label"]) {
    root.querySelectorAll(`[data-i18n-${attribute}]`).forEach(node => {
      node.setAttribute(attribute, t(node.getAttribute(`data-i18n-${attribute}`)));
    });
  }
}

/* Dates and numbers in the interface language's own format. */
function localeTag() { return LANG === "es" ? "es-ES" : undefined; }
