import { state } from "./state.js";

export async function api(url, opts = {}) {
  const { timeout = 15000, ...request } = opts;
  const method = (request.method || "GET").toUpperCase();
  const writesState = method !== "GET" && !url.startsWith("/api/ui/") &&
    !url.startsWith("/api/dialog/");
  const headers = { "Content-Type": "application/json", ...request.headers };
  if (method !== "GET" && state.csrf_token) {
    headers["X-CSRF-Token"] = state.csrf_token;
  }
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeout);
  if (writesState) {
    state.requestVersion++;
    state.pendingWrites++;
  }
  try {
    const response = await fetch(url, {
      ...request,
      headers,
      signal: controller.signal,
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
    return data;
  } catch (error) {
    if (error.name === "AbortError") {
      throw new Error("Server request timed out");
    }
    throw error;
  } finally {
    clearTimeout(timer);
    if (writesState) {
      state.pendingWrites--;
      state.requestVersion++;
    }
  }
}
