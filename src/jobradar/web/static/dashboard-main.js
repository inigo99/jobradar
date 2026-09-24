/* JobRadar dashboard — Wiring: buttons, dialogs and the first load. Loaded last.
   Plain scripts sharing one global scope, loaded in order by dashboard.html. */

/* --------------------------------------------------------------------------
   Wiring
-------------------------------------------------------------------------- */
$("#btn-search").onclick = async () => {
  const node = $("#btn-search");
  node.disabled = true; node.textContent = "Searching…";
  try {
    const result = await api("/api/search", { method: "POST" });
    await refresh();
    toast(`${result.run.kept} jobs kept, ${result.run.new} new, ${result.rejected} filtered out.`);
  } catch (error) { toast(error.message); }
  node.disabled = false; node.textContent = "Search now";
};

$("#btn-sweep").onclick = async () => {
  const node = $("#btn-sweep");
  node.disabled = true; node.textContent = "Checking…";
  try {
    const result = await api("/api/sweep", { method: "POST" });
    await refresh();
    toast(result.summary);
  } catch (error) { toast(error.message); }
  node.disabled = false; node.textContent = "Check closed ads";
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
$("#filter").oninput = () => render();
$("#sort").onchange = () => render();

(async () => {
  await refresh();
  if (!STATE.onboarded) showWizard();
})();
