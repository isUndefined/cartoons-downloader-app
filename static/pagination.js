import { state } from "./state.js";
import { $ } from "./ui.js";

let refresh = () => {};

export function initPagination(onRefresh) {
  refresh = onRefresh;
}

export function renderPagination(name) {
  const box = $(`#${name}Pagination`);
  const info = state.pages?.[name];
  if (!box) return;
  box.classList.toggle(
    "hidden",
    !info || info.pages <= 1 ||
      (name === "discovery" && state.discovery?.running),
  );
  if (!info) return;
  box.innerHTML = `<button type="button" class="dark-btn compact" data-page="${
    info.page - 1
  }" ${info.page <= 1 ? "disabled" : ""}>Previous</button>
    <span>${info.page} / ${info.pages} · ${info.total} ${
    name === "failures" ? "failed jobs" : "videos"
  }</span>
    <button type="button" class="dark-btn compact" data-page="${
    info.page + 1
  }" ${info.page >= info.pages ? "disabled" : ""}>Next</button>`;
  box.querySelectorAll("[data-page]").forEach((button) =>
    button.onclick = async () => {
      if (name === "discovery") state.selected.clear();
      state.pageRequests[name] = Number(button.dataset.page);
      state.requestVersion++;
      box.querySelectorAll("button").forEach((control) =>
        control.disabled = true
      );
      await refresh();
      renderPagination(name);
    }
  );
}
