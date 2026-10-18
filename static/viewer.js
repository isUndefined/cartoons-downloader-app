import { state } from "./state.js";
import { $, toast } from "./ui.js";
function closeVideoViewer() {
  const modal = $("#videoViewerModal"),
    frame = $("#youtubeViewer"),
    video = $("#localVideoViewer");
  frame.src = "about:blank";
  frame.classList.add("hidden");
  try {
    video.pause();
  } catch {}
  video.removeAttribute("src");
  video.load();
  video.classList.add("hidden");
  modal.classList.add("hidden");
}
function openYouTubeVideo(id) {
  const v = state.videos.find((x) => Number(x.id) === Number(id));
  if (!v?.youtube_id) return toast("YouTube video ID is missing");
  $("#videoViewerTitle").textContent = v.title || "YouTube";
  const frame = $("#youtubeViewer"), video = $("#localVideoViewer");
  try {
    video.pause();
  } catch {}
  video.removeAttribute("src");
  video.classList.add("hidden");
  frame.classList.remove("hidden");
  frame.src = `https://www.youtube-nocookie.com/embed/${
    encodeURIComponent(v.youtube_id)
  }?autoplay=1&rel=0&modestbranding=1`;
  $("#videoViewerModal").classList.remove("hidden");
}
function playLocalVideo(id) {
  const v = state.videos.find((x) => Number(x.id) === Number(id));
  if (!v?.file_path) return toast("Downloaded local file was not found");
  $("#videoViewerTitle").textContent = v.title || "Downloaded video";
  const frame = $("#youtubeViewer"), video = $("#localVideoViewer");
  frame.src = "about:blank";
  frame.classList.add("hidden");
  video.classList.remove("hidden");
  video.src = `/media/video/${encodeURIComponent(id)}`;
  $("#videoViewerModal").classList.remove("hidden");
  video.play().catch(() => {});
}
$("#closeVideoViewer").onclick = closeVideoViewer;
$("#videoViewerModal").onclick = (e) => {
  if (e.target.id === "videoViewerModal") closeVideoViewer();
};
document.addEventListener("keydown", (e) => {
  if (
    e.key === "Escape" && !$("#videoViewerModal").classList.contains("hidden")
  ) closeVideoViewer();
});

export { openYouTubeVideo, playLocalVideo };
