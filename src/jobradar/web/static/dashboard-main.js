/* JobRadar dashboard — Wiring: buttons, dialogs and the first load. Loaded last.
   Plain scripts sharing one global scope, loaded in order by dashboard.html. */

/* --------------------------------------------------------------------------
   Wiring
-------------------------------------------------------------------------- */
$("#btn-search").onclick = async () => {
  const node = $("#btn-search");
  node.disabled = true; node.textContent = t("Searching…");
  try {
    const result = await api("/api/search", { method: "POST" });
    await refresh();
    toast(t("{kept} jobs kept, {new} new, {rejected} filtered out.",
            { kept: result.run.kept, new: result.run.new, rejected: result.rejected }));
  } catch (error) { toast(error.message); }
  node.disabled = false; node.textContent = t("Search now");
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
})();
