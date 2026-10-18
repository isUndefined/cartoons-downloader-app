import { state } from "../state.js";
import { $, ACTIVE_JOB, esc, fmtBytes, ICON_LOG } from "../ui.js";
import {
  actualOrRequestedQuality,
  bindMediaActions,
  mediaCard,
  statusLabel,
} from "../cards.js";
import { renderPagination } from "../pagination.js";
let actions = {};
function jobPhase(j) {
  if (j.last_message) {
    return String(j.last_message).replace(/^\[download\]\s*/, "");
  }
  return statusLabel(j.status);
}
function jobMeta(j) {
  let parts = [];
  if (j.downloaded_bytes) {
    parts.push(
      fmtBytes(j.downloaded_bytes) +
        (j.total_bytes ? ` / ${fmtBytes(j.total_bytes)}` : ""),
    );
  }
  if (j.speed) parts.push(`${fmtBytes(j.speed)}/s`);
  if (j.eta != null) parts.push(`ETA ${j.eta}s`);
  return parts.join(" · ") || statusLabel(j.status);
}
function railJob(j) {
  const p = Math.max(0, Math.min(100, Number(j.progress || 0)));
  return `<article class="rail-job"><img src="${
    esc(j.thumbnail_url || "")
  }" alt="" onerror="this.style.visibility='hidden'"><div class="rail-job-main"><h3>${
    esc(j.title || "Download")
  }</h3><div class="job-stage">${
    esc(jobPhase(j))
  }</div><div class="job-percent-row"><div class="progress"><i style="width:${p}%"></i></div><span class="job-percent">${
    p.toFixed(0)
  }%</span></div><div class="job-meta">${
    esc(jobMeta(j))
  }</div></div><div class="job-tools">${
    ACTIVE_JOB.has(j.status)
      ? `<button class="job-tool cancel" data-cancel="${j.id}" title="Cancel">×</button>`
      : ""
  }<button class="job-tool" data-log="${j.id}" title="Open log">${ICON_LOG}</button></div></article>`;
}
function activeJobs() {
  return state.jobs.filter((j) => ACTIVE_JOB.has(j.status)).sort((a, b) =>
    a.position - b.position || a.id - b.id
  );
}
function renderDownloadsRail() {
  const jobs = activeJobs();
  $("#activeDownloadCount").textContent = jobs.length ? `(${jobs.length})` : "";
  const breakdown = {
    queued: 0,
    downloading: 0,
    processing: 0,
    transferring: 0,
    verifying: 0,
  };
  jobs.forEach((j) => {
    if (breakdown[j.status] !== undefined) breakdown[j.status]++;
  });
  const summary = [];
  if (breakdown.downloading) {
    summary.push(`${breakdown.downloading} downloading`);
  }
  if (breakdown.processing) summary.push(`${breakdown.processing} merging`);
  if (breakdown.queued) summary.push(`${breakdown.queued} queued`);
  if (breakdown.transferring + breakdown.verifying) {
    summary.push(`${breakdown.transferring + breakdown.verifying} to device`);
  }
  $("#downloadsSummary").textContent = summary.join(" · ") ||
    "No active downloads";
  const box = $("#downloadsRail");
  box.innerHTML = jobs.length
    ? jobs.map(railJob).join("")
    : '<div class="downloads-empty">Downloads will appear here while they are running.</div>';
  bindJobActions(box);
}
function bindJobActions(root = document) {
  root.querySelectorAll("[data-cancel]").forEach((x) =>
    x.onclick = () => actions.cancelJob(+x.dataset.cancel)
  );
  root.querySelectorAll("[data-log]").forEach((x) =>
    x.onclick = () => actions.openJobLog(+x.dataset.log)
  );
}

function renderDownloadsPage() {
  renderPagination("failures");
  const box = $("#downloadsPage");
  const jobs = state.jobs.filter((j) =>
    !["completed", "cancelled"].includes(j.status)
  ).sort((a, b) => {
    const aa = ACTIVE_JOB.has(a.status) ? 0 : 1,
      bb = ACTIVE_JOB.has(b.status) ? 0 : 1;
    return aa - bb || b.id - a.id;
  });
  box.classList.toggle("hidden", jobs.length === 0);
  $("#downloadsPageEmpty").classList.toggle("hidden", jobs.length > 0);
  box.innerHTML = jobs.map((j) => {
    const p = Math.max(0, Math.min(100, Number(j.progress || 0)));
    return `<article class="page-job"><img src="${
      esc(j.thumbnail_url || "")
    }" alt=""><div class="page-job-title"><h3>${
      esc(j.title || "Download")
    }</h3><p>${esc(j.channel_name || "")} · ${
      esc(actualOrRequestedQuality({}, j))
    }</p></div><div class="page-job-progress"><div class="progress"><i style="width:${p}%"></i></div><p class="page-job-meta">${
      esc(jobPhase(j))
    }</p></div><div><strong>${p.toFixed(0)}%</strong><p class="page-job-meta">${
      esc(jobMeta(j))
    }</p></div><div class="page-job-actions">${
      ACTIVE_JOB.has(j.status)
        ? `<button class="job-tool cancel" data-cancel="${j.id}" title="Cancel">×</button>`
        : ""
    }<button class="job-tool" data-log="${j.id}" title="Open log">${ICON_LOG}</button></div></article>`;
  }).join("");
  bindJobActions(box);
}
function renderDownloaded() {
  const rows = state.videos.filter((v) =>
    (!state.downloaded_ids || state.downloaded_ids.includes(v.id)) &&
    ["downloaded", "device_only"].includes(v.status)
  );
  const grid = $("#downloadedGrid");
  $("#downloadedEmpty").classList.toggle("hidden", rows.length > 0);
  grid.innerHTML = rows.map((v) => mediaCard(v, { downloaded: true })).join("");
  bindMediaActions(grid);
  renderPagination("downloaded");
}

function setDownloadActions(handlers) {
  actions = handlers;
}

export {
  renderDownloaded,
  renderDownloadsPage,
  renderDownloadsRail,
  setDownloadActions,
};
