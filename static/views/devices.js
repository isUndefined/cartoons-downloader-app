import { state } from "../state.js";
import { api } from "../api.js";
import { $, esc, fmtBytes, toast } from "../ui.js";
import { renderBadges } from "../navigation.js";
let actions = {};
function setDeviceActions(handlers) {
  actions = handlers;
}
async function chooseDeviceForVideos(ids) {
  if (!ids?.length) return;
  state.deviceModalVideoIds = [...ids];
  try {
    await refreshDevices({ silent: true });
    openDeviceModal(ids);
  } catch (e) {
    toast(e.message);
  }
}
function openDeviceModal(ids = state.deviceModalVideoIds) {
  state.deviceModalVideoIds = [...(ids || [])];
  const p = $("#devicePicker");
  p.innerHTML = "";
  const online = state.devices.filter((d) => d.state === "device");
  if (!online.length) {
    p.innerHTML =
      '<div class="empty-dark"><h3>No online devices</h3><p>Connect Android by USB and select File transfer (MTP). Devices are detected automatically.</p></div>';
  }
  online.forEach((d) => {
    const x = document.createElement("div");
    x.className = "picker-item";
    x.innerHTML = `<div><strong>${
      esc([d.manufacturer, d.model].filter(Boolean).join(" ") || d.serial)
    }</strong><div class="muted">${esc(d.serial)}${
      d.free_bytes ? " · " + fmtBytes(d.free_bytes) + " free" : ""
    }</div></div><span>→</span>`;
    x.onclick = () =>
      actions.enqueue(state.deviceModalVideoIds, "device", d.serial);
    p.appendChild(x);
  });
  $("#deviceModal").classList.remove("hidden");
}
$("#closeDeviceModal").onclick = () => {
  $("#deviceModal").classList.add("hidden");
  state.deviceModalVideoIds = [];
};
$("#deviceModal").onclick = (e) => {
  if (e.target.id === "deviceModal") {
    $("#deviceModal").classList.add("hidden");
    state.deviceModalVideoIds = [];
  }
};
function renderDevices() {
  const grid = $("#deviceGrid");
  grid.innerHTML = "";
  if (!state.devices.length) {
    grid.innerHTML =
      '<div class="empty-dark"><h3>No devices detected</h3><p>Connect Android by USB, unlock it and select File transfer (MTP). The list updates automatically.</p></div>';
    renderBadges();
    return;
  }
  state.devices.forEach((d) => {
    const online = d.state === "device",
      used = d.total_bytes && d.free_bytes != null
        ? Math.max(0, 100 - d.free_bytes / d.total_bytes * 100)
        : 0;
    const el = document.createElement("article");
    el.className = "device";
    el.innerHTML = `<div class="device-top"><div><h3>${
      esc([d.manufacturer, d.model].filter(Boolean).join(" ") || d.serial)
    }</h3><p>${esc(d.serial)}</p></div><span class="${
      online ? "online" : "offline"
    }">${
      esc(d.state)
    }</span></div><div class="storage"><div class="storage-line"><span>Storage</span><span>${
      d.total_bytes
        ? `${fmtBytes(d.free_bytes)} free of ${fmtBytes(d.total_bytes)}`
        : "Unknown"
    }</span></div><div class="progress"><i style="width:${used}%"></i></div></div><div class="device-actions"><button class="dark-btn" data-scan="${
      esc(d.serial)
    }" ${
      online ? "" : "disabled"
    }>Scan folder</button></div><div class="muted" id="scan-${
      CSS.escape(d.serial)
    }"></div>`;
    grid.appendChild(el);
  });
  grid.querySelectorAll("[data-scan]").forEach((b) =>
    b.onclick = () => scanDevice(b.dataset.scan)
  );
  renderBadges();
}
async function refreshDevices({ silent = false } = {}) {
  if (state.deviceRefreshBusy) return;
  state.deviceRefreshBusy = true;
  const e = $("#deviceError");
  if (!silent) e.classList.add("hidden");
  try {
    const d = await api("/api/devices?refresh=1");
    const before = JSON.stringify(
      state.devices.map((x) => [x.serial, x.state]),
    );
    state.devices = d.devices || [];
    const after = JSON.stringify(state.devices.map((x) => [x.serial, x.state]));
    if (
      !silent || before !== after || state.currentView === "devices" ||
      !$("#deviceModal").classList.contains("hidden")
    ) renderDevices();
    else renderBadges();
    if (!silent) {
      e.classList.toggle("hidden", !d.error);
      e.textContent = d.error || "";
    }
  } catch (err) {
    if (!silent) {
      e.textContent = err.message;
      e.classList.remove("hidden");
    }
  } finally {
    state.deviceRefreshBusy = false;
  }
}
$("#refreshDevicesBtn").onclick = () => refreshDevices({ silent: false });
async function scanDevice(serial) {
  try {
    const d = await api(`/api/devices/${encodeURIComponent(serial)}/files`);
    const el = document.getElementById(`scan-${CSS.escape(serial)}`);
    el.textContent =
      `${d.files.length} file(s), ${d.youtube_ids.length} recognized by YouTube ID · ${d.folder}`;
    toast("Device folder scanned");
  } catch (e) {
    toast(e.message);
  }
}

export {
  chooseDeviceForVideos,
  refreshDevices,
  renderDevices,
  setDeviceActions,
};
