import { $, applyTheme, toast } from "./ui.js";
import { cleanupSelection, setCardActions } from "./cards.js";
import { initNavigation, renderBadges } from "./navigation.js";
import { renderDiscovery, renderDiscoveryStatus } from "./views/discovery.js";
import {
  renderDownloaded,
  renderDownloadsPage,
  renderDownloadsRail,
  setDownloadActions,
} from "./views/downloads.js";
import {
  chooseDeviceForVideos,
  refreshDevices,
  renderDevices,
  setDeviceActions,
} from "./views/devices.js";
import { fillSettings } from "./views/settings.js";
import { loadRetainedSources } from "./views/maintenance.js";
import { openYouTubeVideo, playLocalVideo } from "./viewer.js";
import { state } from "./state.js";
import { api } from "./api.js";
import { latestSnapshot, serialPoll } from "./polling.js";
import { mergeSnapshot, runtimeUrl } from "./sync.js";
import { initPagination } from "./pagination.js";
async function bootstrap() {
  try {
    const data = await api("/api/bootstrap?compact=1");
    Object.assign(state, data);
    mergeSnapshot(state, data);
    applyTheme(state.settings?.theme || "dark");
    renderAll();
    fillSettings();
    renderDiscoveryStatus();
    await updateUiSession("open");
    runtimePoll.start();
    devicePoll.start();
    sessionPoll.start();
    connectionError(null);
  } catch (error) {
    connectionError(error);
    bootstrapTimer = setTimeout(bootstrap, 3000);
  }
}
async function refreshCore() {
  return runtimePoll.refresh();
}

async function beginDiscovery(path) {
  try {
    state.selected.clear();
    const r = await api(path, { method: "POST", body: "{}" });
    state.discovery = r.state;
    $("#discoverBtn").disabled = true;
    $("#emptyDiscoverBtn").disabled = true;
    $("#refreshBtn").disabled = true;
    renderDiscovery();
    pollDiscovery(true);
  } catch (e) {
    toast(e.message);
  }
}
async function startDiscovery() {
  return beginDiscovery("/api/discovery/run");
}
async function refreshDiscovery() {
  return beginDiscovery("/api/discovery/refresh");
}
$("#discoverBtn").onclick = startDiscovery;
$("#emptyDiscoverBtn").onclick = startDiscovery;
$("#refreshBtn").onclick = refreshDiscovery;
function pollDiscovery() {
  renderDiscoveryStatus();
  return refreshCore();
}

async function enqueue(ids, target, serial = null) {
  try {
    const r = await api("/api/jobs", {
      method: "POST",
      body: JSON.stringify({
        video_ids: ids,
        target_type: target,
        device_serial: serial,
      }),
    });
    state.selected.clear();
    state.deviceModalVideoIds = [];
    $("#deviceModal").classList.add("hidden");
    toast(
      `${r.job_ids.length} job(s) added${
        r.skipped_video_ids?.length
          ? ` · ${r.skipped_video_ids.length} already on device`
          : ""
      }`,
    );
    await refreshCore();
  } catch (e) {
    toast(e.message);
  }
}
$("#downloadLocalBtn").onclick = () => enqueue([...state.selected], "local");
$("#downloadDeviceBtn").onclick = () => {
  if (state.selected.size) chooseDeviceForVideos([...state.selected]);
};
async function cancelJob(id) {
  try {
    await api(`/api/jobs/${id}/cancel`, { method: "POST", body: "{}" });
    await refreshCore();
  } catch (e) {
    toast(e.message);
  }
}
async function rejectVideo(id) {
  try {
    await api(`/api/videos/${id}/reject`, { method: "POST", body: "{}" });
    state.selected.delete(id);
    await refreshCore();
  } catch (e) {
    toast(e.message);
  }
}
async function restoreVideo(id) {
  try {
    await api(`/api/videos/${id}/restore`, { method: "POST", body: "{}" });
    await refreshCore();
  } catch (e) {
    toast(e.message);
  }
}

function renderAll() {
  renderDiscovery();
  renderDownloadsPage();
  renderDownloaded();
  renderDevices();
  renderBadges();
}
function connectionError(error) {
  const box = $("#connectionStatus");
  box.classList.toggle("hidden", !error);
  box.textContent = error ? "Connection lost. Reconnecting…" : "";
}
const runtimePoll = serialPoll(async () => {
  await latestSnapshot(
    () => api(runtimeUrl(state)),
    (result) => {
      const catalogChanged = Object.hasOwn(result, "videos");
      const jobsChanged = Object.hasOwn(result, "jobs");
      const wasRunning = !!state.discovery?.running;
      mergeSnapshot(state, result);
      cleanupSelection();
      if (Object.hasOwn(result, "discovery")) renderDiscoveryStatus();
      if (catalogChanged || jobsChanged) renderBadges();
      if (jobsChanged) renderDownloadsRail();
      if (
        catalogChanged ||
        wasRunning !== !!state.discovery?.running
      ) {
        renderDiscovery();
        if (state.currentView === "downloaded") renderDownloaded();
      }
      if (
        (catalogChanged || jobsChanged) && state.currentView === "downloads"
      ) renderDownloadsPage();
    },
    () => state.requestVersion,
    () => state.pendingWrites === 0,
  );
  connectionError(null);
  if (state.currentLogJobId && !$("#logModal").classList.contains("hidden")) {
    await loadJobLog(state.currentLogJobId, false);
  }
}, { onError: connectionError });
const devicePoll = serialPoll(() => refreshDevices({ silent: true }), {
  interval: 4000,
});
const sessionId = crypto.randomUUID();
function updateUiSession(action, keepalive = false) {
  return api("/api/ui/session", {
    method: "POST",
    body: JSON.stringify({ session_id: sessionId, action }),
    keepalive,
  });
}
const sessionPoll = serialPoll(() => updateUiSession("ping"), {
  interval: 10000,
});
let bootstrapTimer = null;
window.addEventListener("pagehide", () => {
  clearTimeout(bootstrapTimer);
  runtimePoll.stop();
  devicePoll.stop();
  sessionPoll.stop();
  if (state.csrf_token) updateUiSession("close", true).catch(() => {});
});
window.addEventListener("pageshow", (event) => {
  if (event.persisted) bootstrap();
});
$("#exitBtn").onclick = async () => {
  try {
    await api("/api/shutdown", { method: "POST", body: "{}" });
    runtimePoll.stop();
    devicePoll.stop();
    sessionPoll.stop();
    $("#connectionStatus").classList.remove("hidden");
    $("#connectionStatus").textContent =
      "Application closed. You can close this window.";
  } catch (error) {
    toast(error.message);
  }
};
let logRevision = 0;
async function loadJobLog(id, scroll = true) {
  const revision = ++logRevision;
  try {
    const d = await api(`/api/jobs/${id}/log`);
    if (revision !== logRevision || state.currentLogJobId !== id) return;
    $("#jobLog").textContent = d.log || "No log output yet.";
    if (scroll) $("#jobLog").scrollTop = $("#jobLog").scrollHeight;
  } catch (e) {
    if (revision !== logRevision || state.currentLogJobId !== id) return;
    $("#jobLog").textContent = e.message;
  }
}
async function openJobLog(id) {
  state.currentLogJobId = id;
  $("#logTitle").textContent = `Job #${id} · yt-dlp / FFmpeg / MTP output`;
  $("#logModal").classList.remove("hidden");
  await loadJobLog(id, true);
}
$("#closeLogModal").onclick = () => {
  $("#logModal").classList.add("hidden");
  state.currentLogJobId = null;
};
$("#refreshLogBtn").onclick = () =>
  state.currentLogJobId && loadJobLog(state.currentLogJobId, true);
$("#logModal").onclick = (e) => {
  if (e.target.id === "logModal") {
    $("#logModal").classList.add("hidden");
    state.currentLogJobId = null;
  }
};
setCardActions({
  renderDiscovery,
  enqueue,
  restoreVideo,
  openYouTubeVideo,
  playLocalVideo,
  chooseDeviceForVideos,
});
setDownloadActions({ cancelJob, openJobLog });
setDeviceActions({ enqueue });
initNavigation({
  settings: loadRetainedSources,
  downloads: renderDownloadsPage,
  downloaded: renderDownloaded,
  devices: renderDevices,
});
initPagination(refreshCore);
bootstrap();
