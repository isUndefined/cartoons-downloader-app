import { api } from "../api.js";
import { $, esc, fmtBytes, toast } from "../ui.js";

let sources = [];
let selected = new Set();
let confirmation = null;
let busy = false;

function updateSelection() {
  const size = sources.filter((item) => selected.has(item.job_id))
    .reduce((total, item) => total + item.size, 0);
  $("#sourceSelection").textContent = selected.size
    ? `${selected.size} sources selected · ${fmtBytes(size)}`
    : "No sources selected";
  $("#reviewSourcesBtn").disabled = busy || !selected.size || !!confirmation;
  $("#refreshSourcesBtn").disabled = busy;
  $("#sourceConfirmation").classList.toggle("hidden", !confirmation);
  for (const input of $("#retainedSources").querySelectorAll("input")) {
    input.disabled = busy || !!confirmation;
  }
  $("#confirmSourceDeletionBtn").disabled = busy;
  $("#cancelSourceDeletionBtn").disabled = busy;
}

async function loadRetainedSources() {
  if (busy) return;
  busy = true;
  confirmation = null;
  selected.clear();
  sources = [];
  $("#retainedSources").replaceChildren();
  $("#sourceMessage").textContent = "Loading retained sources…";
  updateSelection();
  try {
    const data = await api("/api/maintenance/sources");
    sources = data.sources;
    const logs = data.logs;
    $("#logRetention").textContent = `Logs: ${
      fmtBytes(logs.max_bytes)
    } per file, ${logs.backups} backups, ${logs.retention_days} days of inactive history.`;
    $("#sourceMessage").textContent = sources.length
      ? `${sources.length} retained sources · ${
        fmtBytes(sources.reduce((sum, item) => sum + item.size, 0))
      }`
      : "No retained device sources to clean up.";
    $("#retainedSources").innerHTML = sources.map((item) =>
      `<label class="retained-source"><input type="checkbox" data-source-id="${item.job_id}"><span>${
        esc(item.title)
      } · ${fmtBytes(item.size)}<small class="muted">Job ${item.job_id} · ${
        esc(item.status)
      } · ${esc(item.path)}</small>${
        item.files.map((file) =>
          `<small>${esc(file.name)} · ${fmtBytes(file.size)}</small>`
        ).join("")
      }</span></label>`
    ).join("");
  } catch (error) {
    $("#sourceMessage").textContent =
      `Could not load sources: ${error.message}`;
  } finally {
    busy = false;
    updateSelection();
  }
}

$("#retainedSources").onchange = (event) => {
  const id = Number(event.target.dataset.sourceId);
  if (!sources.some((item) => item.job_id === id)) return;
  if (event.target.checked) selected.add(id);
  else selected.delete(id);
  updateSelection();
};
$("#refreshSourcesBtn").onclick = loadRetainedSources;
$("#reviewSourcesBtn").onclick = () => {
  confirmation = sources.filter((item) => selected.has(item.job_id));
  const bytes = confirmation.reduce((sum, item) => sum + item.size, 0);
  $("#sourceConfirmationText").textContent =
    `Permanently delete the ${confirmation.length} selected sources (${
      fmtBytes(bytes)
    }) shown above? These files cannot be restored by the app.`;
  updateSelection();
  $("#cancelSourceDeletionBtn").focus();
};
$("#cancelSourceDeletionBtn").onclick = () => {
  confirmation = null;
  updateSelection();
};
$("#confirmSourceDeletionBtn").onclick = async () => {
  if (busy || !confirmation?.length) return;
  busy = true;
  let message = "";
  updateSelection();
  try {
    const result = await api("/api/maintenance/sources/delete", {
      method: "POST",
      body: JSON.stringify({
        sources: confirmation.map(({ job_id, fingerprint }) => ({
          job_id,
          fingerprint,
        })),
      }),
    });
    toast(
      result.errors.length
        ? `Deleted ${result.deleted.length} sources. Some files could not be removed.`
        : `Deleted ${result.deleted.length} sources`,
    );
    message = result.errors.map((item) => `Job ${item.job_id}: ${item.error}`)
      .join("; ");
  } catch (error) {
    toast(error.message);
    message = error.message;
  } finally {
    busy = false;
    await loadRetainedSources();
    if (message) $("#sourceMessage").textContent = message;
    $("#refreshSourcesBtn").focus();
  }
};

export { loadRetainedSources };
