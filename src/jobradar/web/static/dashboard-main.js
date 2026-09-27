/* JobRadar dashboard — Wiring: buttons, dialogs and the first load. Loaded last.
   Plain scripts sharing one global scope, loaded in order by dashboard.html. */

/* --------------------------------------------------------------------------
   Wiring
-------------------------------------------------------------------------- */
/* The search runs on the server in the background and stores each job as it
   is read; the page asks where it is every two seconds. New jobs are not
   pushed into the board under the reader's cursor: a button offers them. */
let SEARCH_TIMER = null;
let SEARCH_PROGRESS = null;
let SEARCH_SHOWN = null;   // new jobs already on the board; null until the first report

function searchButton(running) {
  const node = $("#btn-search");
  node.disabled = false;
  node.textContent = running ? t("Stop search") : t("Search now");
  node.classList.toggle("primary", !running);
}

function showSearchProgress(progress) {
  $("#search-status").hidden = false;
  SEARCH_PROGRESS = progress;
  if (!progress) { $("#search-text").textContent = t("Starting the search…"); return; }
  if (SEARCH_SHOWN === null) SEARCH_SHOWN = progress.new;
  const total = Math.max(progress.sources_total, 1);
  const part = progress.stage === "reading" && progress.to_read ? progress.read / progress.to_read : 0;
  $("#search-bar").value = Math.min((progress.sources_done + part) / total, 1);
  const where = progress.stage === "reading"
    ? t("{source}: reading ad {read} of {total}",
        { source: progress.source, read: Math.min(progress.read + 1, progress.to_read),
          total: progress.to_read })
    : t("{source}: asking for jobs", { source: progress.source });
  $("#search-text").textContent = [
    t("Source {n} of {total}", { n: Math.min(progress.sources_done + 1, total), total }),
    where,
    tn(progress.kept, "{n} job kept", "{n} jobs kept"),
  ].join(" · ");
  const waiting = progress.new - SEARCH_SHOWN;
  const show = $("#search-show");
  show.hidden = waiting <= 0;
  show.textContent = tn(waiting, "Show {n} new job", "Show {n} new jobs");
}

async function followSearch() {
  let status;
  try { status = await api("/api/search"); }
  catch (error) { SEARCH_TIMER = setTimeout(followSearch, 4000); return; }
  if (status.running) {
    searchButton(true);
    showSearchProgress(status.progress);
    SEARCH_TIMER = setTimeout(followSearch, 2000);
    return;
  }
  SEARCH_TIMER = null;
  SEARCH_SHOWN = null;
  $("#search-status").hidden = true;
  $("#search-show").hidden = true;
  searchButton(false);
  await refresh();
  const outcome = status.outcome;
  if (!outcome) return;
  if (!outcome.ok) { toast(outcome.detail); return; }
  const summary = t("{kept} jobs kept, {new} new, {rejected} filtered out.",
                    { kept: outcome.run.kept, new: outcome.run.new, rejected: outcome.rejected });
  toast(outcome.run.cancelled ? `${t("Search stopped.")} ${summary}` : summary);
}

$("#btn-search").onclick = async () => {
  const node = $("#btn-search");
  node.disabled = true;
  if (SEARCH_TIMER !== null) {   // running: this button stops it
    node.textContent = t("Stopping…");
    try { await api("/api/search/cancel", { method: "POST" }); } catch (error) { toast(error.message); }
    return;
  }
  node.textContent = t("Searching…");
  try { await api("/api/search", { method: "POST" }); }
  catch (error) { toast(error.message); searchButton(false); return; }
  showSearchProgress(null);
  SEARCH_TIMER = setTimeout(followSearch, 500);
};

$("#search-show").onclick = async () => {
  if (SEARCH_PROGRESS) SEARCH_SHOWN = SEARCH_PROGRESS.new;
  $("#search-show").hidden = true;
  await refresh();
};

$("#btn-sweep").onclick = async () => {
  const node = $("#btn-sweep");
  node.disabled = true; node.textContent = t("Checking…");
  try {
    const result = await api("/api/sweep", { method: "POST" });
    await refresh();
    toast(result.summary);
  } catch (error) { toast(error.message); }
  node.disabled = false; node.textContent = t("Check closed ads");
};

$("#btn-mail").onclick = checkMail;
$("#btn-add-job").onclick = () => {
  if (!STATE.onboarded) { toast(t("Finish setting up first.")); return; }
  showManualJob();
};

$("#btn-settings").onclick = () => {
  $("#settings-body").innerHTML = "";
  $("#settings-body").append(settingsBody());
  $("#settings").showModal();
};
$("#settings-close").onclick = () => $("#settings").close();
$("#settings-save").onclick = async () => {
  try { await saveSettings(); } catch (error) { toast(error.message); }
};
wireFilters();
$("#sort").onchange = () => render();

(async () => {
  chooseLanguage();   // the browser's language until the saved choice arrives
  await refresh();
  if (!STATE.onboarded) showWizard();
  // A search started before this page was (re)loaded: follow it.
  if (STATE.running && STATE.running.search) SEARCH_TIMER = setTimeout(followSearch, 0);
})();
