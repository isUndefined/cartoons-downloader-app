// One request at a time, with at most one requested follow-up. Timers start
// after completion, so a slow server cannot accumulate requests.
export function serialPoll(task, { interval = 800, onError = () => {} } = {}) {
  let current = null;
  let pending = false;
  let timer = null;
  let stopped = true;

  function refresh() {
    clearTimeout(timer);
    pending = true;
    if (current) return current;
    current = (async () => {
      while (pending) {
        pending = false;
        try {
          await task();
        } catch (error) {
          onError(error);
        }
      }
    })().finally(() => {
      current = null;
      if (!stopped) timer = setTimeout(refresh, interval);
    });
    return current;
  }

  return {
    refresh,
    start() {
      stopped = false;
      return refresh();
    },
    stop() {
      stopped = true;
      pending = false;
      clearTimeout(timer);
    },
  };
}

export async function latestSnapshot(
  load,
  apply,
  revision,
  canApply = () => true,
) {
  const before = revision();
  const data = await load();
  if (before !== revision() || !canApply()) return false;
  apply(data);
  return true;
}
