import { state } from "./state.js";
import {
  $,
  ACTIVE_JOB,
  esc,
  fmtDuration,
  ICON_DEVICE,
  ICON_DOWNLOAD,
  ICON_PLAY,
  ICON_RETRY,
  ICON_YOUTUBE,
} from "./ui.js";
let actions = {};
function jobForVideo(videoId) {
  const jobs = state.jobs.filter((j) => Number(j.video_id) === Number(videoId));
  const active =
    jobs.filter((j) => ACTIVE_JOB.has(j.status)).sort((a, b) => b.id - a.id)[0];
  if (active) return active;
  const latest = state.videos.find((v) => Number(v.id) === Number(videoId))
    ?.latest_job;
  return [...jobs, ...(latest ? [latest] : [])].sort((a, b) =>
    b.id - a.id
  )[0] || null;
}
function displayStatus(v) {
  const j = jobForVideo(v.id);
  if (j && ACTIVE_JOB.has(j.status)) return j.status;
  if (j && j.status === "failed" && v.status === "pending") return "failed";
  return v.status || "pending";
}
function statusLabel(s) {
  return ({
    pending: "New",
    queued: "Queued",
    downloading: "Downloading",
    processing: "Merging",
    transferring: "Sending",
    verifying: "Verifying",
    downloaded: "Downloaded",
    device_only: "On device",
    failed: "Failed",
    unavailable: "Unavailable",
    rejected: "Rejected",
    cancelled: "Cancelled",
    completed: "Completed",
  })[s] || s;
}
function selectable(v) {
  let s = displayStatus(v);
  return s === "pending" || s === "failed";
}
function cleanupSelection() {
  for (const id of [...state.selected]) {
    const v = state.videos.find((x) => x.id === id);
    if (!v || !selectable(v)) state.selected.delete(id);
  }
}
function actualOrRequestedQuality(v, j) {
  if (["downloaded", "device_only"].includes(v.status) && v.actual_quality) {
    return `${Number(v.actual_quality)}p`;
  }
  if (j?.actual_quality) return `${Number(j.actual_quality)}p`;
  if (j?.requested_quality) return `${Number(j.requested_quality)}p`;
  return `${Number(state.settings?.default_download_quality || 720)}p`;
}
function mediaCard(v, { downloaded = false } = {}) {
  const s = displayStatus(v),
    j = jobForVideo(v.id),
    canSelect = !downloaded && selectable(v),
    quality = actualOrRequestedQuality(v, j);
  let action = "";
  if (canSelect) {
    action =
      `<button class="card-top-btn card-download" data-enqueue-one="${v.id}" title="Download" aria-label="Download">${ICON_DOWNLOAD}</button>`;
  } else if (!downloaded && s === "unavailable") {
    action =
      `<button class="card-top-btn card-download" data-restore="${v.id}" title="Retry" aria-label="Retry">${ICON_RETRY}</button>`;
  }
  const local = downloaded && v.status === "downloaded" && v.file_path;
  const youtubeButton =
    `<button class="card-top-btn card-youtube" type="button" data-view-youtube="${v.id}" title="Watch on YouTube" aria-label="Watch on YouTube">${ICON_YOUTUBE}</button>`;
  const downloadedActions = downloaded
    ? `<div class="card-top-actions downloaded-actions">${youtubeButton}${
      local
        ? `<button class="card-top-btn card-play" type="button" data-play-local="${v.id}" title="Play downloaded" aria-label="Play downloaded">${ICON_PLAY}</button><button class="card-top-btn card-device" type="button" data-send-local="${v.id}" title="Send to device" aria-label="Send to device">${ICON_DEVICE}</button>`
        : ""
    }</div>`
    : `<div class="card-top-actions">${action}${youtubeButton}</div>`;
  const durationBadge = Number(v.duration) > 0
    ? `<span class="media-duration">${fmtDuration(v.duration)}</span>`
    : "";
  const qualityBadge = `<span class="media-quality-inline">${
    esc(quality)
  }</span>`;
  return `<article class="media-card ${
    state.selected.has(v.id) ? "selected" : ""
  } ${canSelect ? "has-select" : ""}" data-card-id="${v.id}">
    ${
    canSelect
      ? `<input class="media-check" type="checkbox" data-select="${v.id}" ${
        state.selected.has(v.id) ? "checked" : ""
      } aria-label="Select ${esc(v.title)}">`
      : ""
  }
    <img src="${
    esc(v.thumbnail_url || "")
  }" alt="" onerror="this.style.display='none'">
    ${durationBadge}
    ${
    s !== "pending" && s !== "downloaded" && s !== "device_only"
      ? `<span class="media-status ${esc(s)}">${esc(statusLabel(s))}</span>`
      : ""
  }
    <div class="media-copy"><div class="media-quality-row">${qualityBadge}</div><h3 title="${
    esc(v.title)
  }">${esc(v.title)}</h3><p class="media-meta"><span class="media-channel">${
    esc(v.channel_name || "Unknown channel")
  }</span></p></div>
    ${downloadedActions}
  </article>`;
}
function closeCardMenus(exceptId = null) {
  document.querySelectorAll("[data-card-menu]").forEach((menu) => {
    if (String(menu.dataset.cardMenu) !== String(exceptId)) {
      menu.classList.add("hidden");
      menu.closest(".media-card")?.classList.remove("menu-open");
    }
  });
  document.querySelectorAll("[data-menu-toggle]").forEach((btn) => {
    if (String(btn.dataset.menuToggle) !== String(exceptId)) {
      btn.setAttribute("aria-expanded", "false");
    }
  });
}
function bindMediaActions(root = document) {
  root.querySelectorAll("[data-select]").forEach((x) =>
    x.onchange = () => {
      let id = +x.dataset.select;
      x.checked ? state.selected.add(id) : state.selected.delete(id);
      actions.renderDiscovery();
    }
  );
  root.querySelectorAll("[data-enqueue-one]").forEach((x) =>
    x.onclick = (e) => {
      e.preventDefault();
      actions.enqueue([+x.dataset.enqueueOne], "local");
    }
  );
  root.querySelectorAll("[data-restore]").forEach((x) =>
    x.onclick = (e) => {
      e.preventDefault();
      actions.restoreVideo(+x.dataset.restore);
    }
  );
  root.querySelectorAll("[data-menu-toggle]").forEach((x) =>
    x.onclick = (e) => {
      e.preventDefault();
      e.stopPropagation();
      const id = x.dataset.menuToggle,
        menu = root.querySelector(`[data-card-menu="${id}"]`),
        open = menu && !menu.classList.contains("hidden");
      closeCardMenus();
      if (menu && !open) {
        menu.classList.remove("hidden");
        menu.closest(".media-card")?.classList.add("menu-open");
        x.setAttribute("aria-expanded", "true");
      }
    }
  );
  root.querySelectorAll("[data-view-youtube]").forEach((x) =>
    x.onclick = (e) => {
      e.preventDefault();
      e.stopPropagation();
      closeCardMenus();
      actions.openYouTubeVideo(+x.dataset.viewYoutube);
    }
  );
  root.querySelectorAll("[data-play-local]").forEach((x) =>
    x.onclick = (e) => {
      e.preventDefault();
      e.stopPropagation();
      closeCardMenus();
      actions.playLocalVideo(+x.dataset.playLocal);
    }
  );
  root.querySelectorAll("[data-send-local]").forEach((x) =>
    x.onclick = (e) => {
      e.preventDefault();
      e.stopPropagation();
      closeCardMenus();
      actions.chooseDeviceForVideos([+x.dataset.sendLocal]);
    }
  );
}
document.addEventListener("click", () => closeCardMenus());
function setCardActions(handlers) {
  actions = handlers;
}

export {
  actualOrRequestedQuality,
  bindMediaActions,
  cleanupSelection,
  displayStatus,
  jobForVideo,
  mediaCard,
  selectable,
  setCardActions,
  statusLabel,
};
