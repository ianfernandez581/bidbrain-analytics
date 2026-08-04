'use strict';
/*
 * src/brain/persist.js — durable state for The Grid.
 *
 * THE PROBLEM THIS SOLVES. On Cloud Run the container filesystem is ephemeral and the
 * image ships without data/ (see .dockerignore), so the SQLite DB lived in /tmp and
 * died with the instance. Every cold start rebuilt it from config/central-import.json,
 * which is why the deployed Grid only ever showed sheet-era numbers and why "Last
 * synced" always read "never synced" — there was nowhere for a sync to land.
 *
 * THE SHAPE. The whole database is 96 KB (89 campaigns + 31 provenance rows), so it is
 * kept as ONE object in GCS rather than a database service: load it on boot, write it
 * back (debounced) after any mutation. This is the same pattern the platform already
 * uses for status.json and the per-client definitions blobs. Cloud SQL for 89 rows
 * would be an always-on instance and a VPC connector to move a file smaller than a
 * photo.
 *
 * OFF BY DEFAULT. With no GRID_STATE_BUCKET set, every function here is a no-op and
 * the local dev DB at grid-core/data/ behaves exactly as it always has.
 *
 * CONCURRENCY. Writes carry an ifGenerationMatch precondition, so a second instance
 * can never silently clobber the first. central-grid runs --min-instances=1 and is
 * super-admin-only, so overlap is confined to the seconds around a deploy; if a
 * conflict does happen the upload is REFUSED and logged loudly rather than guessed at.
 */
const fs = require('fs');
const path = require('path');
const { execFileSync } = require('child_process');

const BUCKET = process.env.GRID_STATE_BUCKET || '';
const OBJECT = process.env.GRID_STATE_OBJECT || 'grid-state/brain-historical.db';
const SAVE_DEBOUNCE_MS = Number(process.env.GRID_STATE_DEBOUNCE_MS || 4000);
const RESTORE_TIMEOUT_MS = Number(process.env.GRID_STATE_RESTORE_TIMEOUT_MS || 30000);

const enabled = () => !!BUCKET;

let generation = null;      // last generation we know of; the write precondition
let dbPath = null;          // set by restoreSync, reused by every save
let checkpoint = null;      // fn the db module gives us to fold WAL into the main file
let timer = null, saving = false, dirtyWhileSaving = false, stopped = false;

/**
 * Download the state file over dbPath BEFORE the database is opened. Synchronous by
 * necessity — see scripts/state-restore.js for why. Never throws: a restore failure
 * degrades to a fresh DB (the old behaviour) instead of a server that will not boot.
 */
function restoreSync(targetPath) {
  dbPath = targetPath;
  if (!enabled()) return { restored: false, reason: 'no GRID_STATE_BUCKET — local file only' };
  const script = path.join(__dirname, '..', '..', 'scripts', 'state-restore.js');
  try {
    const out = execFileSync(process.execPath, [script, BUCKET, OBJECT, targetPath],
      { encoding: 'utf8', timeout: RESTORE_TIMEOUT_MS, stdio: ['ignore', 'pipe', 'pipe'] });
    generation = (out || '').trim() || null;
    const kb = (fs.existsSync(targetPath) ? fs.statSync(targetPath).size / 1024 : 0).toFixed(0);
    console.log(`[STATE] restored gs://${BUCKET}/${OBJECT} (${kb} KB, generation ${generation})`);
    return { restored: true, generation };
  } catch (e) {
    if (e && e.status === 3) {   // no object yet: a first run, not a fault
      console.log(`[STATE] gs://${BUCKET}/${OBJECT} does not exist yet — starting a fresh DB; the first write creates it`);
      return { restored: false, reason: 'first run' };
    }
    const detail = String((e && e.stderr) || (e && e.message) || e).trim().slice(0, 300);
    console.error(`[STATE][WARN] could not restore gs://${BUCKET}/${OBJECT} — CONTINUING ON AN EMPTY DB. ${detail}`);
    return { restored: false, reason: detail };
  }
}

/** The db module hands us a way to fold the WAL back into the .db file before upload. */
function setCheckpoint(fn) { checkpoint = fn; }

/** Mark the DB changed. Debounced so a burst of edits uploads once. */
function saveSoon() {
  if (!enabled() || stopped) return;
  if (saving) { dirtyWhileSaving = true; return; }
  if (timer) clearTimeout(timer);
  timer = setTimeout(() => { timer = null; save().catch(() => {}); }, SAVE_DEBOUNCE_MS);
  if (timer.unref) timer.unref();     // never hold the process open just to flush
}

/** Upload now. Returns {ok} / {ok:false, reason}. Never throws. */
async function save() {
  if (!enabled() || !dbPath) return { ok: false, reason: 'disabled' };
  if (saving) { dirtyWhileSaving = true; return { ok: false, reason: 'already-saving' }; }
  saving = true;
  try {
    if (checkpoint) { try { checkpoint(); } catch (e) { /* a busy WAL still uploads fine */ } }
    if (!fs.existsSync(dbPath)) return { ok: false, reason: 'no db file' };
    const { Storage } = require('@google-cloud/storage');
    const file = new Storage().bucket(BUCKET).file(OBJECT);
    // generation 0 means "only if it does not exist yet" — the correct precondition
    // for the very first write, and it stops two cold instances both creating it.
    const precondition = generation === null ? { ifGenerationMatch: 0 } : { ifGenerationMatch: Number(generation) };
    await file.save(fs.readFileSync(dbPath), {
      resumable: false, contentType: 'application/x-sqlite3', preconditionOpts: precondition
    });
    const [md] = await file.getMetadata();
    generation = String(md.generation || '');
    return { ok: true, generation };
  } catch (e) {
    const code = e && (e.code || e.status);
    if (code === 412) {
      // Someone else wrote since our last read. Do NOT overwrite their state blindly.
      console.error('[STATE][CONFLICT] another instance wrote the state file — this instance did NOT upload. ' +
                    'Its in-memory DB is now diverged; restart it to pick up the newer state.');
      return { ok: false, reason: 'generation-conflict' };
    }
    console.error('[STATE][WARN] save failed: ' + String((e && e.message) || e).slice(0, 300));
    return { ok: false, reason: String((e && e.message) || e).slice(0, 300) };
  } finally {
    saving = false;
    if (dirtyWhileSaving) { dirtyWhileSaving = false; saveSoon(); }
  }
}

/** Flush on shutdown: Cloud Run sends SIGTERM before it kills the instance. */
function installShutdownFlush() {
  if (!enabled()) return;
  const flush = (sig) => {
    stopped = true;
    if (timer) { clearTimeout(timer); timer = null; }
    save().then(r => {
      console.log(`[STATE] ${sig} flush: ${r.ok ? 'saved (generation ' + r.generation + ')' : 'not saved — ' + r.reason}`);
      process.exit(0);
    });
  };
  process.on('SIGTERM', () => flush('SIGTERM'));
  process.on('SIGINT', () => flush('SIGINT'));
}

module.exports = { enabled, restoreSync, setCheckpoint, saveSoon, save, installShutdownFlush,
                   get bucket() { return BUCKET; }, get object() { return OBJECT; },
                   get generation() { return generation; } };
