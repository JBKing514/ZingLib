/**
 * Decides when a page turn is allowed to reach the screen.
 *
 * The reader used to swap pages the moment the page number changed: the old
 * page left the DOM, the new one mounted, and the screen was empty until its
 * bytes arrived and decoded. Under a fast tap that is a blank frame per turn,
 * and in a two-page spread it can show one half of a pair while the other is
 * still loading.
 *
 * So the page number the reader *navigates* to and the page it *shows* are two
 * different things. Every turn asks this queue to prepare a key (one page, or
 * both halves of a spread); the queue loads them, and only then does it commit
 * the key to the caller. Three properties come out of that:
 *
 *   - the old page stays painted until the new one is decoded, because nothing
 *     changes on screen before the commit;
 *   - a spread commits as a pair, never half of one;
 *   - a burst of turns only ever commits its last target -- each request takes
 *     a token and a stale one is dropped when its loads finish.
 *
 * A load that fails, or one that never settles, still commits: showing a broken
 * page beats freezing on the previous one forever.
 */
export function createPageCommitQueue({
  load,
  onCommit,
  timeoutMs = 1500,
  schedule = (fn, ms) => setTimeout(fn, ms),
  cancel = (id) => clearTimeout(id),
}) {
  let token = 0;
  let committed = null;
  let timer = null;

  function clearTimer() {
    if (timer !== null) {
      cancel(timer);
      timer = null;
    }
  }

  /**
   * Ask for `key` to be shown, loading `urls` first.
   *
   * Returns a promise for tests and for callers that want to await the turn;
   * the UI only cares about the commit.
   */
  function request(key, urls = []) {
    const mine = ++token;
    clearTimer();

    // Asking for what is already on screen is a no-op rather than a reload.
    if (key === committed) return Promise.resolve(false);

    const settle = (ready) => {
      if (mine !== token) return false;
      clearTimer();
      if (key === committed) return false;
      committed = key;
      onCommit(key, { ready });
      return true;
    };

    const loads = Promise.all(
      urls.map((url) => Promise.resolve()
        .then(() => load(url))
        .then((ok) => Boolean(ok))
        .catch(() => false))
    ).then((results) => settle(results.every(Boolean)));

    // A stalled request must not hold the reader hostage.
    timer = schedule(() => {
      timer = null;
      if (mine !== token) return;
      settle(false);
    }, timeoutMs);

    return loads;
  }

  /** The reader jumped somewhere the queue knows nothing about (route enter). */
  function reset(key = null) {
    token += 1;
    committed = key;
    clearTimer();
  }

  function getCommitted() {
    return committed;
  }

  return { request, reset, getCommitted };
}
