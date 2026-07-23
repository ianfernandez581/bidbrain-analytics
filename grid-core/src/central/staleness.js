/*
 * src/central/staleness.js — THE single config location for data-freshness
 * thresholds + the shared per-client sync-state rollup (Phase 4 item 4).
 *
 * Every surface that judges "how old is the synced data" (Central's last-synced
 * banner, Pulse's client rail, the Executive cards, the row-level mixed-state
 * markers) reads THESE constants — never a local copy. Change the thresholds
 * here and every tab moves together.
 *
 * States:
 *   'never'  no row of the scope has EVER synced (metricsSource all sheet-import)
 *            — this is NOT "fresh": it must always render as unsynced, loudly.
 *   'fresh'  newest sync within STALE_WARN_MS
 *   'warn'   newest sync older than STALE_WARN_MS (amber)
 *   'red'    newest sync older than STALE_RED_MS (red)
 *
 * Pure + dependency-free (Node + browser), same dual-export pattern as match.js.
 */
(function (root, factory) {
  var api = factory();
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  if (typeof window !== 'undefined') window.CentralStaleness = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  var STALE_WARN_MS = 6 * 60 * 60 * 1000;    // > 6h  → amber
  var STALE_RED_MS = 24 * 60 * 60 * 1000;    // > 24h → red

  function ts(v) {
    if (v == null || v === '') return null;
    var t = typeof v === 'number' ? v : Date.parse(v);
    return isFinite(t) ? t : null;
  }

  /** Classify one sync timestamp (ms | ISO string | null). null → 'never'. */
  function classify(lastSynced, nowMs) {
    var t = ts(lastSynced);
    if (t == null) return 'never';
    var age = (nowMs == null ? Date.now() : nowMs) - t;
    if (age > STALE_RED_MS) return 'red';
    if (age > STALE_WARN_MS) return 'warn';
    return 'fresh';
  }

  /** Human age label: 'never' | '35m ago' | '3h ago' | '2d ago'. */
  function agoLabel(lastSynced, nowMs) {
    var t = ts(lastSynced);
    if (t == null) return 'never';
    var mins = Math.max(0, Math.round(((nowMs == null ? Date.now() : nowMs) - t) / 60000));
    if (mins < 60) return mins + 'm ago';
    var h = Math.floor(mins / 60);
    if (h < 48) return h + 'h ago';
    return Math.floor(h / 24) + 'd ago';
  }

  /**
   * Roll up ONE client's campaign rows into a sync state. Accepts raw DB rows or
   * Pulse spine rows — reads only metricsSource + lastSyncedAt.
   *   { total, live, sheet, newest(ms|null), state, mixed }
   * state = 'never' when NO row is live (sheet-import-only clients are never-synced,
   * not fresh); else classify(newest). mixed = some rows live, some still sheet —
   * the §9 containment state that used to be invisible.
   */
  function clientSyncState(rows, nowMs) {
    var live = 0, sheet = 0, newest = null;
    (rows || []).forEach(function (r) {
      if (!r) return;
      var src = String(r.metricsSource || '').toLowerCase();
      if (src === 'bq') live++; else sheet++;
      var t = ts(r.lastSyncedAt);
      if (t != null && (newest == null || t > newest)) newest = t;
    });
    var total = live + sheet;
    var state = (live === 0) ? 'never' : classify(newest, nowMs);
    return { total: total, live: live, sheet: sheet, newest: newest, state: state, mixed: live > 0 && sheet > 0 };
  }

  return {
    STALE_WARN_MS: STALE_WARN_MS,
    STALE_RED_MS: STALE_RED_MS,
    classify: classify,
    agoLabel: agoLabel,
    clientSyncState: clientSyncState
  };
});
