export function replayRequestWasCancelled(reason, signal) {
  return Boolean(signal?.aborted || reason?.name === "AbortError");
}
