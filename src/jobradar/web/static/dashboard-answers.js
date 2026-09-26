/* JobRadar dashboard — Form answers and the answer bank.
   Plain scripts sharing one global scope, loaded in order by dashboard.html.

   One thread per job: paste a question from the application form, get an
   answer drawn from the profile, refine it in the same thread ("shorter",
   "less formal"). Answers worth keeping go to the bank, and come back as
   precedents when another job asks something similar. Every answer shows the
   warnings of jobradar/documents/review.py; none of them blocks anything. */

/* A list of review warnings, or nothing. Shared with the letter editor. */
function warningsBlock(warnings) {
  if (!warnings || !warnings.length) return null;
  const label = { error: t("Check"), warning: t("Careful"), info: t("Note") };
  return el("div", { className: "warnings" }, ...warnings.map(w =>
    el("div", { className: "lint-finding" },
      el("span", { className: "sev " + w.severity }, (label[w.severity] || w.severity) + " · "),
      el("span", {}, w.message),
      w.hint ? el("div", { className: "hint" }, w.hint) : null)));
}

const unitLabel = unit => ({ characters: t("characters"), words: t("words") }[unit] || unit);

function answersUrl(job, suffix = "") {
  return `/api/jobs/${encodeURIComponent(job.id)}/answers${suffix}`;
}

async function openAnswers(job, card) {
  const thread = await api(answersUrl(job));
  const bank = await api("/api/answer-bank");
  renderAnswers(job, card, thread, bank.entries);
}

function renderAnswers(job, card, thread, bank, note = "") {
  const output = $(".job-output", card);
  const redraw = async (next, message = "") => {
    const fresh = await api("/api/answer-bank");
    renderAnswers(job, card, next || await api(answersUrl(job)), fresh.entries, message);
  };

  const messages = el("div", { className: "chat" });
  thread.messages.forEach((message, index) => {
    if (message.role === "question") {
      messages.append(el("div", { className: "bubble question" },
        el("span", { className: "who" }, t("You")), message.text));
      return;
    }
    messages.append(answerBubble(job, thread, message, index, redraw));
  });
  if (!thread.messages.length) {
    messages.append(el("p", { className: "hint" },
      t("Paste a question from this job's application form — \u201cWhy do you want to work here?\u201d, \u201cTell us about a project you are proud of\u201d, \u201cExpected salary?\u201d. If the answer does not fit, ask for a change in the same thread: shorter, less formal, in English.")));
  }

  const box = el("textarea", { className: "question-box", rows: 3,
                               placeholder: t("Paste the question… (Ctrl+Enter to send)") });
  const send = async () => {
    const question = box.value.trim();
    if (!question) { toast(t("Write the question first")); return; }
    const result = await api(answersUrl(job), { method: "POST", body: JSON.stringify({ question }) });
    const from = (result.precedents || [])[0];
    await redraw(result, from
      ? (from.company ? t("Adapted from your answer to \u201c{question}\u201d for {company}.",
                          { question: from.question, company: from.company })
                      : t("Adapted from your answer to \u201c{question}\u201d.", { question: from.question }))
      : result.llm_generated ? "" : t("No language model configured: this is a starting point to edit."));
  };
  box.addEventListener("keydown", event => {
    if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) { event.preventDefault(); sendButton.click(); }
  });
  const sendButton = button(t("Get an answer"), send);
  sendButton.className = "primary";

  const limit = el("input", { type: "number", min: "1", step: "10", className: "limit",
                              value: thread.limit ?? "", placeholder: "—" });
  const unit = selectFrom("", thread.unit, [["characters", t("characters")], ["words", t("words")]]);
  const saveLimit = async () => {
    const next = await api(answersUrl(job, "/limit"), { method: "PUT", body: JSON.stringify({
      limit: limit.value ? Number(limit.value) : null, unit: unit.value }) });
    await redraw(next);
  };
  limit.addEventListener("change", saveLimit);
  unit.addEventListener("change", saveLimit);

  output.innerHTML = "";
  appendAll(output,
    el("h4", { style: "margin:14px 0 4px" }, t("Form answers")),
    note ? el("p", { className: "hint" }, note) : null,
    messages,
    box,
    el("div", { className: "actions" },
      el("label", { className: "inline" }, t("The form's limit")), limit, unit,
      thread.messages.length ? button(t("Clear the thread"), async () => {
        if (!confirm(t("Delete this job's questions and answers? Saved bank entries stay."))) return;
        await api(answersUrl(job), { method: "DELETE" });
        await redraw();
      }) : null,
      sendButton),
    bankBlock(bank, redraw),
  );
}

function answerBubble(job, thread, message, index, redraw) {
  const bubble = el("div", { className: "bubble answer" });
  const over = thread.limit && message.length > thread.limit;
  const counter = el("span", { className: "count" + (over ? " over" : "") },
    (thread.limit
      ? t("{n} {unit} of {limit}", { n: message.length, unit: unitLabel(thread.unit), limit: thread.limit })
      : t("{n} {unit}", { n: message.length, unit: unitLabel(thread.unit) }))
    + (over ? " — " + t("over the limit") : ""));
  const edit = () => {
    const area = el("textarea", { rows: 6 });
    area.value = message.text;
    bubble.replaceChildren(el("span", { className: "who" }, t("Editing the answer")), area,
      el("div", { className: "actions" },
        button(t("Save"), async () => redraw(await api(answersUrl(job, `/${index}`),
          { method: "PUT", body: JSON.stringify({ text: area.value }) }))),
        button(t("Cancel"), async () => redraw(thread))));
  };
  appendAll(bubble,
    el("span", { className: "who" }, message.edited_at ? t("Answer (edited)") : t("Answer")),
    el("div", { className: "answer-text" }, message.text),
    warningsBlock(message.warnings),
    el("div", { className: "actions" }, counter,
      button(t("Copy"), async () => { await navigator.clipboard.writeText(message.text); toast(t("Copied")); }),
      button(t("Edit"), async () => edit()),
      message.in_bank ? el("span", { className: "hint" }, t("In the bank"))
        : button(t("Save to the bank"), async () => {
          await api(answersUrl(job, `/${index}/bank`), { method: "POST" });
          await redraw(thread, t("Saved to the bank."));
        })));
  return bubble;
}

/* Saved answers: edit the question or the answer, or delete them. */
function bankBlock(bank, redraw) {
  if (!bank.length) return null;
  const rows = bank.map(entry => {
    const row = el("div", { className: "bank-row" });
    const show = () => row.replaceChildren(
      el("p", { className: "bank-q" }, entry.question),
      el("p", {}, entry.answer),
      el("div", { className: "hint" },
        [entry.company, entry.job_title, String(entry.saved_at).slice(0, 10)]
          .filter(Boolean).join(" · ") + (entry.edited_at ? " · " + t("edited") : ""), " ",
        button(t("Copy"), async () => { await navigator.clipboard.writeText(entry.answer); toast(t("Copied")); }),
        button(t("Edit"), async () => editRow()),
        button(t("Delete"), async () => {
          await api(`/api/answer-bank/${encodeURIComponent(entry.id)}`, { method: "DELETE" });
          await redraw();
        })));
    const editRow = () => {
      const question = el("input", { value: entry.question });
      const answer = el("textarea", { rows: 5 });
      answer.value = entry.answer;
      row.replaceChildren(el("label", {}, t("Question")), question, el("label", {}, t("Answer")), answer,
        el("div", { className: "actions" },
          button(t("Save"), async () => {
            await api(`/api/answer-bank/${encodeURIComponent(entry.id)}`, { method: "PUT",
              body: JSON.stringify({ question: question.value, answer: answer.value }) });
            await redraw();
          }),
          button(t("Cancel"), async () => show())));
    };
    show();
    return row;
  });
  return el("details", { className: "detail bank" },
    el("summary", {}, t("Answer bank ({n})", { n: bank.length })),
    el("div", { className: "detail-body" }, ...rows));
}
