import { state } from "../state.js";
import { api } from "../api.js";
import { $, applyTheme, toast } from "../ui.js";
import { renderDiscovery } from "./discovery.js";
function fillSettings() {
  const s = state.settings;
  if (!s) return;
  $("#targetPending").value = s.target_pending;
  $("#minDuration").value = s.min_duration_minutes;
  $("#maxPerChannel").value = s.max_results_per_channel;
  $("#includeRecent").checked = s.discovery_include_recent;
  $("#defaultDownloadQuality").value = String(
    s.default_download_quality || 720,
  );
  $("#appTheme").value = s.theme === "light" ? "light" : "dark";
  $("#downloadFolder").value = s.download_folder || "";
  $("#deviceFolder").value = s.device_folder || "";
  $("#queries").value = (s.search_queries || []).map((x) => x.query).join("\n");
  $("#romanianHints").value = (s.romanian_hints || []).map((x) =>
    `${x.value} | ${x.weight}`
  ).join("\n");
  $("#excludeHints").value = (s.exclude_hints || []).map((x) => x.value).join(
    "\n",
  );
  $("#channelRules").value = (s.channel_rules || []).map((x) =>
    `${x.rule} | ${x.channel_key}${
      x.rule === "trusted" ? ` | ${x.weight || 25}` : ""
    }`
  ).join("\n");
}
function lines(id) {
  return $(id).value.split(/\r?\n/).map((x) => x.trim()).filter(Boolean);
}
$("#browseDownloadFolderBtn").onclick = async () => {
  const btn = $("#browseDownloadFolderBtn");
  btn.disabled = true;
  try {
    const d = await api("/api/dialog/folder", {
      method: "POST",
      body: JSON.stringify({ initial: $("#downloadFolder").value.trim() }),
      timeout: 310000,
    });
    if (d.selected && d.path) {
      $("#downloadFolder").value = d.path;
      toast("Download folder selected");
    }
  } catch (e) {
    toast(e.message);
  } finally {
    btn.disabled = false;
  }
};
$("#saveSettingsBtn").onclick = async () => {
  for (const id of ["#targetPending", "#minDuration", "#maxPerChannel"]) {
    if (!$(id).reportValidity()) return;
  }
  const romanian = lines("#romanianHints").map((line) => {
    let [value, w] = line.split("|").map((x) => x.trim());
    return { value, weight: Number(w || 10), enabled: true };
  });
  const rules = lines("#channelRules").map((line) => {
    let [rule, channel_key, w] = line.split("|").map((x) => x.trim());
    return { rule, channel_key, weight: Number(w || 25) };
  }).filter((x) => ["trusted", "blocked"].includes(x.rule) && x.channel_key);
  const payload = {
    target_pending: +$("#targetPending").value,
    min_duration_minutes: +$("#minDuration").value,
    max_results_per_channel: +$("#maxPerChannel").value,
    discovery_include_recent: $("#includeRecent").checked,
    default_download_quality: +$("#defaultDownloadQuality").value,
    theme: $("#appTheme").value,
    download_folder: $("#downloadFolder").value.trim(),
    device_folder: $("#deviceFolder").value.trim(),
    search_queries: lines("#queries"),
    romanian_hints: romanian,
    exclude_hints: lines("#excludeHints"),
    channel_rules: rules,
  };
  try {
    const d = await api("/api/settings", {
      method: "PUT",
      body: JSON.stringify(payload),
    });
    state.settings = d.settings;
    applyTheme(state.settings?.theme || "dark");
    $("#settingsSaved").textContent = "Saved";
    setTimeout(() => $("#settingsSaved").textContent = "", 2000);
    renderDiscovery();
    toast("Settings saved");
  } catch (e) {
    toast(e.message);
  }
};

export { fillSettings };
