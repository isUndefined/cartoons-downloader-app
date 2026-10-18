import { state } from "../state.js";
import { $, setSystem } from "../ui.js";
import {
  bindMediaActions,
  cleanupSelection,
  displayStatus,
  mediaCard,
} from "../cards.js";
import { renderBadges } from "../navigation.js";
import { renderDownloadsRail } from "./downloads.js";
import { renderPagination } from "../pagination.js";
function discoverySkeleton(count = 8) {
  return Array.from(
    { length: count },
    () =>
      `<article class="media-card skeleton-card" aria-hidden="true"><div class="skeleton-thumb"></div><div class="skeleton-copy"><span class="skeleton-line skeleton-title"></span><span class="skeleton-line skeleton-meta"></span></div><span class="skeleton-pill"></span></article>`,
  ).join("");
}
function renderDiscovery() {
  cleanupSelection();
  renderBadges();
  const grid = $("#discoveryGrid");
  const running = Boolean(state.discovery?.running);
  renderPagination("discovery");
  if (running) {
    grid.innerHTML = discoverySkeleton(window.innerWidth >= 1650 ? 10 : 8);
    $("#discoveryEmpty").classList.add("hidden");
    $("#newCount").textContent = "—";
    $("#targetCount").textContent = Number(
      state.settings?.target_pending || 10,
    );
    state.selected.clear();
    updateSelectionButtons();
    renderDownloadsRail();
    return;
  }
  const rows = state.videos.filter((v) =>
    (!state.discovery_ids || state.discovery_ids.includes(v.id)) &&
    ["pending", "failed", "unavailable"].includes(displayStatus(v))
  );
  grid.innerHTML = rows.map((v) => mediaCard(v)).join("");
  bindMediaActions(grid);
  $("#discoveryEmpty").classList.toggle("hidden", rows.length > 0);
  $("#emptyMessage").textContent =
    "Run Discovery to fill the list with new cartoons.";
  const pending = state.counts?.ready ??
    state.videos.filter((v) => displayStatus(v) === "pending").length;
  $("#newCount").textContent = pending;
  $("#targetCount").textContent = Number(state.settings?.target_pending || 10);
  updateSelectionButtons();
  renderDownloadsRail();
}
function updateSelectionButtons() {
  const n = state.selected.size;
  for (const el of [$("#downloadLocalBtn"), $("#downloadDeviceBtn")]) {
    el.classList.toggle("hidden", !n);
  }
  $("#downloadLocalBtn").disabled = !n;
  $("#downloadDeviceBtn").disabled = !n;
  $("#downloadLocalBtn").textContent = n
    ? `↓ Download selected (${n})`
    : "↓ Download selected";
  $("#downloadDeviceBtn").textContent = n
    ? `▣ Send to device (${n})`
    : "▣ Send to device";
}

function renderDiscoveryStatus() {
  const d = state.discovery || {};
  $("#discoveryProgress").classList.toggle(
    "hidden",
    !d.running && !d.error && d.progress !== 1,
  );
  $("#discoveryMessage").textContent = d.message || "Discovery";
  const percent = Math.round((d.progress || 0) * 100);
  $("#discoveryPercent").textContent = `${percent}%`;
  $("#discoveryBar").style.width = `${percent}%`;
  $("#discoveryError").classList.toggle("hidden", !d.error);
  $("#discoveryError").textContent = d.error || "";
  for (const id of ["#discoverBtn", "#emptyDiscoverBtn", "#refreshBtn"]) {
    $(id).disabled = !!d.running;
  }
  setSystem(
    d.running
      ? (d.mode === "refresh" ? "Refreshing discovery" : "Discovery running")
      : "Ready",
  );
}

export { renderDiscovery, renderDiscoveryStatus };
