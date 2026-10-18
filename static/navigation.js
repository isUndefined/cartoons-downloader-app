import { state } from "./state.js";
import { $, $$, ACTIVE_JOB } from "./ui.js";
import { displayStatus } from "./cards.js";
let renderers = {};
function counts() {
  const c = { pending: 0, active: 0, downloaded: 0, device: 0 };
  for (const v of state.videos) {
    let s = displayStatus(v);
    if (s === "pending" || s === "failed" || s === "unavailable") c.pending++;
    if (ACTIVE_JOB.has(s)) c.active++;
    if (v.status === "downloaded" || v.status === "device_only") c.downloaded++;
  }
  if (state.counts) Object.assign(c, state.counts);
  c.device = state.devices.filter((d) => d.state === "device").length;
  return c;
}
function renderBadges() {
  const c = counts();
  for (
    const [id, n] of [["discoveryBadge", c.pending], ["queueBadge", c.active], [
      "downloadedBadge",
      c.downloaded,
    ], ["devicesBadge", c.device]]
  ) {
    const el = document.getElementById(id);
    if (!el) continue;
    el.textContent = n;
    el.classList.toggle("hidden", !n);
  }
}
const VIEW_META = {
  discovery: ["Discovery", "Fresh cartoons ready to browse"],
  downloads: ["Downloads", "Current queue and recent jobs"],
  downloaded: ["Downloaded", "Completed local and device downloads"],
  devices: ["Devices", "Android devices connected through Windows MTP"],
  settings: ["Settings", "Discovery, quality and storage preferences"],
};
function showView(name) {
  state.currentView = name;
  $$("[data-view]").forEach((x) =>
    x.classList.toggle("active", x.dataset.view === name)
  );
  $$(".view").forEach((x) =>
    x.classList.toggle("active", x.id === `view-${name}`)
  );
  $("#discoveryActions").classList.toggle("hidden", name !== "discovery");
  const meta = VIEW_META[name] || VIEW_META.discovery;
  $("#currentSection").textContent = meta[0];
  $("#currentSectionHint").textContent = meta[1];
  if (name === "downloads") renderers.downloads();
  if (name === "downloaded") renderers.downloaded();
  if (name === "devices") renderers.devices();
  if (name === "settings") renderers.settings();
}
function initNavigation(views) {
  renderers = views;
  $$("[data-view]").forEach((b) => b.onclick = () => showView(b.dataset.view));
}

export { initNavigation, renderBadges, showView };
