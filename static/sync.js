// Apply section versions only together with their accepted response. Discarded
// responses must not acknowledge data that the page has never displayed.
export function mergeSnapshot(target, result) {
  for (
    const key of [
      "videos",
      "jobs",
      "discovery",
      "counts",
      "pages",
      "versions",
      "discovery_ids",
      "downloaded_ids",
    ]
  ) {
    if (Object.hasOwn(result, key)) target[key] = result[key];
  }
  if (result.pages) {
    for (const [name, info] of Object.entries(result.pages)) {
      target.pageRequests[name] = info.page;
    }
  }
}

export function runtimeUrl(target) {
  const query = new URLSearchParams({ compact: "1" });
  for (const [name, page] of Object.entries(target.pageRequests)) {
    query.set(name + "_page", page);
  }
  for (const [name, version] of Object.entries(target.versions || {})) {
    query.set(name + "_version", version);
  }
  return "/api/runtime?" + query;
}
