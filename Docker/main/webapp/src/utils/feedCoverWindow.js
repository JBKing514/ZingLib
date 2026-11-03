export const FEED_THUMB_PLACEHOLDER =
  "data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7";

export function createFeedCoverWindow({
  createObserver = typeof IntersectionObserver === "function"
    ? (callback) => new IntersectionObserver(callback, { rootMargin: "1200px 0px" })
    : null,
  setTimer = setTimeout,
  clearTimer = clearTimeout,
  now = () => Date.now(),
  releaseDelay = 400,
  onDeferredChange = () => {},
} = {}) {
  const records = new Map();
  const byNode = new Map();
  const pending = new Set();
  let timer = null;
  let active = true;
  let disposed = false;

  function defer(record, value) {
    record.deferred = value;
    onDeferredChange(record.key, value);
    if (Boolean(record.item._thumbDeferred) !== value) record.item._thumbDeferred = value;
  }

  function cancel(record) {
    pending.delete(record);
    if (!pending.size && timer !== null) {
      clearTimer(timer);
      timer = null;
    }
  }

  function unregister(key) {
    const record = records.get(key);
    if (!record) return;
    cancel(record);
    observer?.unobserve(record.node);
    byNode.delete(record.node);
    records.delete(key);
    onDeferredChange(key, false);
  }

  function flush() {
    timer = null;
    if (!active || disposed) return;
    const at = now();
    let next = Infinity;
    for (const record of pending) {
      if (record.near || records.get(record.key) !== record) {
        pending.delete(record);
      } else if (!record.node.isConnected) {
        unregister(record.key);
      } else if (record.releaseAt > at) {
        next = Math.min(next, record.releaseAt);
      } else {
        pending.delete(record);
        defer(record, true);
      }
    }
    if (pending.size) timer = setTimer(flush, Math.max(0, next - at));
  }

  const observer = createObserver?.((entries) => {
    if (!active || disposed) return;
    for (const entry of entries) {
      const record = byNode.get(entry.target);
      if (!record) continue;
      record.near = entry.isIntersecting;
      if (record.near) {
        cancel(record);
        defer(record, false);
      } else if (!record.deferred) {
        record.releaseAt = now() + releaseDelay;
        pending.add(record);
      }
    }
    // Batch releases into one timer/render turn rather than one per card.
    if (pending.size && timer === null) timer = setTimer(flush, releaseDelay);
  });

  return {
    register(key, node, item) {
      if (disposed) return;
      if (!node || node.nodeType !== 1 || !item?.thumb_url) {
        unregister(key);
        return;
      }
      if (!observer) {
        if (item._thumbDeferred) item._thumbDeferred = false;
        return;
      }
      const old = records.get(key);
      if (old?.node === node) {
        old.item = item;
        defer(old, old.deferred);
        return;
      }
      unregister(key);
      const record = { key, node, item, near: false, deferred: Boolean(item._thumbDeferred) };
      records.set(key, record);
      byNode.set(node, record);
      defer(record, record.deferred);
      if (active) observer.observe(node);
      else defer(record, true);
    },
    pause() {
      if (disposed) return;
      active = false;
      observer?.disconnect();
      if (timer !== null) clearTimer(timer);
      timer = null;
      pending.clear();
      for (const record of records.values()) defer(record, true);
    },
    resume() {
      if (disposed || active) return;
      active = true;
      for (const record of records.values()) observer?.observe(record.node);
    },
    dispose() {
      this.pause();
      disposed = true;
      records.clear();
      byNode.clear();
    },
  };
}
