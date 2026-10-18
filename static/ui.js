const $ = (s) => document.querySelector(s),
  $$ = (s) => [...document.querySelectorAll(s)];
const esc = (s) =>
  String(s ?? "").replace(
    /[&<>"']/g,
    (m) => ({
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#039;",
    }[m]),
  );
const fmtBytes = (n) => {
  n = Number(n || 0);
  if (!n) return "—";
  let u = ["B", "KB", "MB", "GB", "TB"], i = 0;
  while (n >= 1024 && i < u.length - 1) {
    n /= 1024;
    i++;
  }
  return `${n.toFixed(i ? 1 : 0)} ${u[i]}`;
};
const fmtDuration = (s) => {
  if (!s) return "—";
  s = Math.round(Number(s));
  let h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), x = s % 60;
  return h
    ? `${h}:${String(m).padStart(2, "0")}:${String(x).padStart(2, "0")}`
    : `${m}:${String(x).padStart(2, "0")}`;
};
function applyTheme(theme) {
  const value = theme === "light" ? "light" : "dark";
  document.documentElement.dataset.theme = value;
  document.documentElement.style.colorScheme = value;
  window.chrome?.webview?.postMessage(`theme:${value}`);
}
const ACTIVE_JOB = new Set([
  "queued",
  "downloading",
  "processing",
  "transferring",
  "verifying",
]);
const ICON_LOG =
  '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 3h8l4 4v14H6z"/><path d="M14 3v5h5M9 12h6M9 16h6"/></svg>';
const ICON_YOUTUBE =
  '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M21 12s0-4-1-5-2-1-8-1-8 0-8 1-1 5-1 5 0 4 1 5 2 1 8 1s6 0 8-1c1-1 1-5 1-5Z"/><path d="m10 9 5 3-5 3Z"/></svg>';
const ICON_PLAY =
  '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="m10 8 6 4-6 4Z"/></svg>';
const ICON_DEVICE =
  '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="7" y="2.5" width="10" height="19" rx="2"/><path d="M10 18.5h4"/></svg>';
const ICON_DOWNLOAD =
  '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3v11"/><path d="m7.5 10 4.5 4.5 4.5-4.5"/><path d="M5 20h14"/></svg>';
const ICON_RETRY =
  '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M20 11a8 8 0 1 0-2.34 5.66"/><path d="M20 4v7h-7"/></svg>';
function toast(msg) {
  let t = $("#toast");
  t.textContent = msg;
  t.classList.remove("hidden");
  clearTimeout(t._x);
  t._x = setTimeout(() => t.classList.add("hidden"), 3200);
}
function setSystem(msg) {
  $("#systemStatus").textContent = msg;
}

export {
  $,
  $$,
  ACTIVE_JOB,
  applyTheme,
  esc,
  fmtBytes,
  fmtDuration,
  ICON_DEVICE,
  ICON_DOWNLOAD,
  ICON_LOG,
  ICON_PLAY,
  ICON_RETRY,
  ICON_YOUTUBE,
  setSystem,
  toast,
};
