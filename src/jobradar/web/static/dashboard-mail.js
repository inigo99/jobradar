/* JobRadar dashboard — Replies read from the inbox.
   Plain scripts sharing one global scope, loaded in order by dashboard.html.

   JobRadar never changes an application's stage from an email: a message that
   reads like a rejection only *suggests* it, and an interview time is offered
   as a calendar file to add by hand. */

const mailKindLabel = kind => ({ rejection: t("Rejection"), advance: t("Next step"),
                                 acknowledgement: t("Acknowledged") }[kind] || kind);

function mailBlock(job) {
  const news = (STATE.mail || {})[job.id];
  if (!news) return null;
  const when = String(news.received_at || "").slice(0, 10);
  const box = el("div", { className: "mailnews " + news.kind },
    el("div", {},
      el("span", { className: "chip mail-" + news.kind }, mailKindLabel(news.kind)),
      " ", el("span", { className: "hint" }, `${when} · ${news.sender}`)),
    el("div", {}, el("b", {}, news.subject)),
    news.excerpt ? el("blockquote", {}, news.excerpt) : null,
    news.link ? el("a", { href: news.link, target: "_blank", rel: "noopener" }, t("Open the thread")) : null,
  );
  if (news.kind === "rejection" && job.stage !== "rejected") {
    box.append(el("p", { className: "hint" },
      t("This reads like a rejection. If it is, mark it so it stops counting as a live process."),
      " ", button(t("Mark as rejected"), () =>
        track(job, { status: "applied", stage: "rejected", applied_on: job.applied_on,
                     notes: job.notes }))));
  }
  if (news.interview_at) {
    const at = new Date(news.interview_at);
    box.append(el("p", {},
      el("b", {}, t("Proposed interview:")), " ",
      at.toLocaleString(localeTag(), { dateStyle: "full", timeStyle: "short" }), " ",
      el("a", { href: `/api/jobs/${encodeURIComponent(job.id)}/interview.ics` },
        t("Add to calendar (.ics)"))));
    if (news.interview_text && news.interview_text !== news.excerpt) box.append(el("p", { className: "hint" }, `“${news.interview_text}”`));
  }
  return box;
}

/* Replies about applications that are not marked as applied here: usually
   applications made outside JobRadar, or a job whose company name differs. */
function orphansBlock() {
  const orphans = STATE.mail_orphans || [];
  if (!orphans.length) return null;
  return el("div", { className: "panel orphans" },
    el("h3", {}, tn(orphans.length, "{n} reply in your email about applications not marked as applied here",
                    "{n} replies in your email about applications not marked as applied here")),
    el("p", { className: "hint" },
      t("If one matches a job on the board, open it and mark it as applied so its replies are tracked; otherwise it was probably an application made elsewhere.")),
    el("ul", {}, ...orphans.slice(0, 15).map(news =>
      el("li", {},
        el("span", { className: "chip mail-" + news.kind }, mailKindLabel(news.kind)),
        " ", el("b", {}, news.company_hint), " — ", news.subject, " ",
        el("span", { className: "hint" }, String(news.received_at).slice(0, 10)),
        news.link ? [" ", el("a", { href: news.link, target: "_blank", rel: "noopener" }, t("open"))] : null))),
  );
}

async function checkMail() {
  const node = $("#btn-mail");
  node.disabled = true; node.textContent = t("Reading mail…");
  try {
    const result = await api("/api/mail/check", { method: "POST" });
    await refresh();
    toast(result.summary, 6000);
  } catch (error) { toast(error.message, 8000); }
  node.disabled = false; node.textContent = t("Check email");
}
