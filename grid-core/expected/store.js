// Greenlight analysis store. An ANALYSIS is a named workspace for one
// campaign: its own file dump (persists across runs) plus a run history.
// This is what stops files from different campaigns mixing - a new analysis
// is a fresh, isolated container.
//
// Layout (local, under GREENLIGHT_DUMPS_DIR):
//   analyses/<id>/analysis.json       {id, name, auto_named, created_at, archived_at, last_run}
//   analyses/<id>/files/**            the uploaded dump for this campaign
//   analyses/<id>/runs/<runId>/out/*  artifacts of one run
//   analyses/<id>/runs/<runId>/results.json
//
// GCS mirror (optional, GREENLIGHT_BUCKET): every write mirrors to
// gs://<bucket>/analyses/... best-effort; on boot the small analysis.json
// index is pulled down, and files/artifacts are fetched lazily on first read.
// Local FS stays the source of truth for the running instance - a mirror
// failure is logged loudly, never breaks a request. On Cloud Run this is what
// makes the runs library survive cold starts (/tmp does not).
'use strict';

const fs = require('fs');
const path = require('path');
const crypto = require('crypto');

const DUMPS = process.env.GREENLIGHT_DUMPS_DIR || path.join(__dirname, 'dumps');
const ANALYSES = path.join(DUMPS, 'analyses');
const BUCKET = process.env.GREENLIGHT_BUCKET || '';

// ---------------------------------------------------------------- gcs mirror
let _bucket = null;
function gcs() {
  if (!BUCKET) return null;
  if (_bucket) return _bucket;
  try {
    const { Storage } = require('@google-cloud/storage');
    _bucket = new Storage().bucket(BUCKET);
  } catch (e) {
    console.error('[greenlight][gcs] client init failed, mirror disabled:', e.message);
  }
  return _bucket;
}

function relKey(abs) {
  return path.relative(DUMPS, abs).split(path.sep).join('/');
}

async function mirrorUpload(abs) {
  const b = gcs();
  if (!b) return;
  try { await b.upload(abs, { destination: relKey(abs) }); }
  catch (e) { console.error(`[greenlight][gcs] upload failed for ${relKey(abs)}:`, e.message); }
}

async function mirrorUploadDir(dir) {
  if (!gcs() || !fs.existsSync(dir)) return;
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    const p = path.join(dir, e.name);
    if (e.isDirectory()) await mirrorUploadDir(p);
    else await mirrorUpload(p);
  }
}

async function mirrorDeletePrefix(prefix) {
  const b = gcs();
  if (!b) return;
  try { await b.deleteFiles({ prefix, force: true }); }
  catch (e) { console.error(`[greenlight][gcs] delete failed for ${prefix}:`, e.message); }
}

/** Fetch one object down to its local path if it is not already there. */
async function mirrorFetch(abs) {
  const b = gcs();
  if (!b || fs.existsSync(abs)) return fs.existsSync(abs);
  try {
    fs.mkdirSync(path.dirname(abs), { recursive: true });
    await b.file(relKey(abs)).download({ destination: abs });
    return true;
  } catch { return false; }
}

/** Pull an analysis's UPLOADED DUMP back down from the mirror.
 *
 *  On Cloud Run the local copy lives in /tmp, which is wiped on every instance
 *  restart. The mirror is the durable copy, so without this an analysis comes
 *  back listing ZERO files: a re-run then analyses only whatever is uploaded
 *  next and returns a confident, fully-cited baseline built from a fraction of
 *  the paperwork. Nothing looks wrong, which is worse than an error.
 *
 *  Cheap when warm: one list call, and downloads only what is missing. */
async function ensureFiles(id) {
  const b = gcs();
  if (!b) return { pulled: 0, remote: null };
  const prefix = `analyses/${id}/files/`;
  try {
    const [objects] = await b.getFiles({ prefix });
    const missing = objects.filter((f) => !f.name.endsWith('/') && !fs.existsSync(path.join(DUMPS, ...f.name.split('/'))));
    // bounded parallelism: a big dump is hundreds of files, serial is minutes
    const queue = missing.slice();
    const worker = async () => {
      for (let f = queue.shift(); f; f = queue.shift()) {
        const abs = path.join(DUMPS, ...f.name.split('/'));
        fs.mkdirSync(path.dirname(abs), { recursive: true });
        await f.download({ destination: abs });
      }
    };
    await Promise.all(Array.from({ length: Math.min(8, queue.length) }, worker));
    if (missing.length) console.log(`[greenlight][gcs] rehydrated ${missing.length} file(s) for analysis ${id}`);
    return { pulled: missing.length, remote: objects.filter((f) => !f.name.endsWith('/')).length };
  } catch (e) {
    console.error(`[greenlight][gcs] rehydrate failed for ${id}:`, e.message);
    return { pulled: 0, remote: null };
  }
}

/** Boot sync: pull every analyses/<id>/analysis.json so the library lists
 *  runs made by previous instances. Artifacts come down lazily on read. */
async function bootSync() {
  const b = gcs();
  if (!b) return;
  try {
    const [files] = await b.getFiles({ prefix: 'analyses/' });
    let pulled = 0;
    for (const f of files) {
      if (!/^analyses\/[a-f0-9]+\/(analysis\.json|runs\/[a-f0-9]+\/results\.json)$/.test(f.name)) continue;
      const abs = path.join(DUMPS, ...f.name.split('/'));
      if (fs.existsSync(abs)) continue;
      fs.mkdirSync(path.dirname(abs), { recursive: true });
      await f.download({ destination: abs });
      pulled++;
    }
    if (pulled) console.log(`[greenlight][gcs] boot sync pulled ${pulled} metadata file(s) from gs://${BUCKET}`);
  } catch (e) {
    console.error('[greenlight][gcs] boot sync failed (continuing local-only):', e.message);
  }
}

// ---------------------------------------------------------------- fs helpers
function walk(dir, base, acc) {
  if (!fs.existsSync(dir)) return acc;
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    const p = path.join(dir, e.name);
    if (e.isDirectory()) walk(p, base, acc);
    else if (e.name.toLowerCase() !== 'desktop.ini') {
      acc.push({ name: path.relative(base, p).split(path.sep).join('/'), bytes: fs.statSync(p).size });
    }
  }
  return acc;
}

function aDir(id) { return path.join(ANALYSES, id); }
function aFilesDir(id) { return path.join(aDir(id), 'files'); }
function aRunDir(id, runId) { return path.join(aDir(id), 'runs', runId); }
function aJsonPath(id) { return path.join(aDir(id), 'analysis.json'); }

function readAnalysis(id) {
  try { return JSON.parse(fs.readFileSync(aJsonPath(id), 'utf8')); }
  catch { return null; }
}

function writeAnalysis(a) {
  fs.mkdirSync(aDir(a.id), { recursive: true });
  fs.writeFileSync(aJsonPath(a.id), JSON.stringify(a, null, 2));
  mirrorUpload(aJsonPath(a.id));
  return a;
}

// ---------------------------------------------------------------- API
function createAnalysis(name) {
  const id = crypto.randomBytes(6).toString('hex');
  const auto = !(name && String(name).trim());
  const a = {
    id,
    name: auto ? 'Untitled - ' + new Date().toISOString().slice(0, 10) : String(name).trim().slice(0, 120),
    auto_named: auto,
    created_at: new Date().toISOString(),
    archived_at: null,
    last_run: null,
  };
  writeAnalysis(a);
  fs.mkdirSync(aFilesDir(id), { recursive: true });
  return a;
}

function listAnalyses() {
  if (!fs.existsSync(ANALYSES)) return [];
  const out = [];
  for (const id of fs.readdirSync(ANALYSES)) {
    if (!/^[a-f0-9]+$/.test(id)) continue;
    const a = readAnalysis(id);
    if (!a) continue;
    const runsDir = path.join(aDir(id), 'runs');
    const runIds = fs.existsSync(runsDir) ? fs.readdirSync(runsDir).filter((r) => /^[a-f0-9]+$/.test(r)) : [];
    out.push({
      id: a.id,
      name: a.name,
      auto_named: !!a.auto_named,
      created_at: a.created_at,
      archived_at: a.archived_at || null,
      runs: runIds.length,
      last_run: a.last_run || null,
      files: walk(aFilesDir(id), aFilesDir(id), []).length,
    });
  }
  out.sort((x, y) => String(y.last_run && y.last_run.at || y.created_at).localeCompare(String(x.last_run && x.last_run.at || x.created_at)));
  return out;
}

function analysisDetail(id) {
  const a = readAnalysis(id);
  if (!a) return null;
  const runsDir = path.join(aDir(id), 'runs');
  const runs = [];
  if (fs.existsSync(runsDir)) {
    for (const rid of fs.readdirSync(runsDir)) {
      if (!/^[a-f0-9]+$/.test(rid)) continue;
      let label = rid;
      let at = null;
      try {
        const res = JSON.parse(fs.readFileSync(path.join(aRunDir(id, rid), 'results.json'), 'utf8'));
        at = res.run && res.run.finished_at || null;
        label = (res.meta ? `${res.meta.client} ${res.meta.job}` : rid);
      } catch { /* run without results (failed mid-archive) stays id-labelled */ }
      runs.push({ id: rid, at, label });
    }
    runs.sort((x, y) => String(y.at || '').localeCompare(String(x.at || '')));
  }
  return { analysis: a, files: walk(aFilesDir(id), aFilesDir(id), []), runs };
}

function renameAnalysis(id, name) {
  const a = readAnalysis(id);
  if (!a) return null;
  a.name = String(name || '').trim().slice(0, 120) || a.name;
  a.auto_named = false;
  return writeAnalysis(a);
}

/** Called after a successful run: refresh last_run, and if the analysis was
 *  never named by a human, adopt the extracted client + job as its name. */
function recordRun(id, runId, filesHash, extractedLabel) {
  const a = readAnalysis(id);
  if (!a) return null;
  a.last_run = { id: runId, at: new Date().toISOString(), files_hash: filesHash };
  if (a.auto_named && extractedLabel) a.name = extractedLabel.slice(0, 120);
  return writeAnalysis(a);
}

function setArchived(id, archived) {
  const a = readAnalysis(id);
  if (!a) return null;
  a.archived_at = archived ? new Date().toISOString() : null;
  return writeAnalysis(a);
}

function deleteAnalysis(id) {
  if (!readAnalysis(id)) return false;
  fs.rmSync(aDir(id), { recursive: true, force: true });
  mirrorDeletePrefix(`analyses/${id}/`);
  return true;
}

// Uploaded names may carry subfolders; never let one escape the files dir.
function safeRel(name) {
  const clean = String(name || '').replace(/\\/g, '/').split('/')
    .filter((seg) => seg && seg !== '.' && seg !== '..' && !/^[A-Za-z]:$/.test(seg))
    .join('/');
  return clean || null;
}

async function stageFile(id, name, dataB64, maxBytes) {
  if (!readAnalysis(id)) throw new Error('unknown analysis');
  const rel = safeRel(name);
  if (!rel) throw new Error('missing or invalid file name');
  const data = Buffer.from(String(dataB64 || ''), 'base64');
  if (!data.length) throw new Error('empty file payload');
  if (data.length > maxBytes) throw new Error(`file too large (${(data.length / 1048576).toFixed(1)}MB; per-file limit ${(maxBytes / 1048576).toFixed(0)}MB)`);
  const dest = path.join(aFilesDir(id), ...rel.split('/'));
  fs.mkdirSync(path.dirname(dest), { recursive: true });
  fs.writeFileSync(dest, data);
  // Awaited on purpose: the mirror is the only durable copy, so returning 200
  // before it lands means a crash in that window loses the file silently.
  await mirrorUpload(dest);
  clearSkipped(id, rel);   // a retry that succeeded clears its own warning
  recordFileCount(id);
  return { staged: rel, bytes: data.length };
}

function removeFile(id, name) {
  const rel = safeRel(name);
  if (!rel) throw new Error('missing or invalid file name');
  const target = path.join(aFilesDir(id), ...rel.split('/'));
  if (!target.startsWith(aFilesDir(id))) throw new Error('invalid path');
  if (fs.existsSync(target)) {
    fs.rmSync(target, { force: true });
    mirrorDeletePrefix(relKey(target));
  }
  recordFileCount(id);
  return { removed: rel };
}

/** Record a file the browser could NOT upload (over the size limit, or the
 *  request failed). This used to live only in the page's memory and was wiped
 *  the moment the upload batch finished, so the dump quietly shrank with no
 *  explanation. Persisted here it survives the refresh and a reload. */
function recordSkipped(id, name, bytes, reason) {
  const a = readAnalysis(id);
  if (!a) throw new Error('unknown analysis');
  const rel = safeRel(name);
  if (!rel) throw new Error('missing or invalid file name');
  a.skipped = (a.skipped || []).filter((s) => s.name !== rel);
  a.skipped.push({ name: rel, bytes: Number(bytes) || 0, reason: String(reason || 'upload failed').slice(0, 200), at: new Date().toISOString() });
  writeAnalysis(a);
  return { skipped: rel };
}

/** Drop a name from the skipped list (it arrived after all, or was dismissed). */
function clearSkipped(id, name) {
  const a = readAnalysis(id);
  if (!a || !a.skipped) return { cleared: 0 };
  const rel = name ? safeRel(name) : null;
  const before = a.skipped.length;
  a.skipped = rel ? a.skipped.filter((s) => s.name !== rel) : [];
  if (a.skipped.length !== before) writeAnalysis(a);
  return { cleared: before - a.skipped.length };
}

/** How many files this analysis is SUPPOSED to have, stamped whenever the set
 *  changes. A local count below it means the dump did not come back (see
 *  ensureFiles) and the run must refuse rather than analyse a partial dump. */
function recordFileCount(id) {
  const a = readAnalysis(id);
  if (!a) return null;
  a.files_expected = walk(aFilesDir(id), aFilesDir(id), []).length;
  return writeAnalysis(a);
}

function localFileCount(id) {
  return walk(aFilesDir(id), aFilesDir(id), []).length;
}

/** Content hash of an analysis's file set - the re-run guard compares this
 *  against last_run.files_hash so an unchanged dump prompts before spending
 *  another model call. */
function filesHash(id) {
  const files = walk(aFilesDir(id), aFilesDir(id), []).sort((a, b) => a.name.localeCompare(b.name));
  const h = crypto.createHash('sha256');
  for (const f of files) {
    h.update(f.name);
    h.update(String(f.bytes));
    h.update(fs.readFileSync(path.join(aFilesDir(id), ...f.name.split('/'))));
  }
  return files.length ? h.digest('hex') : null;
}

// ------------------------------------------------- last-extract slot
// The model call is the expensive stage. After every successful extraction its
// artifacts are saved here so a failed BUILD can be retried without paying for
// (and waiting on) another model call. One slot per analysis, newest wins.
const EXTRACT_FILES = ['manifest.json', 'plan.json', 'findings.json', 'messages.json', 'chase_messages.md'];

function extractSlot(id) { return path.join(aDir(id), 'last_extract'); }

async function saveExtract(id, outDir, filesHash) {
  const dest = extractSlot(id);
  fs.mkdirSync(dest, { recursive: true });
  for (const f of EXTRACT_FILES) {
    const src = path.join(outDir, f);
    if (fs.existsSync(src)) fs.copyFileSync(src, path.join(dest, f));
  }
  fs.writeFileSync(path.join(dest, 'meta.json'), JSON.stringify({ at: new Date().toISOString(), files_hash: filesHash || null }, null, 2));
  await mirrorUploadDir(dest);
}

/** The slot's meta (or null), pulling from the GCS mirror on a fresh instance. */
async function extractMeta(id) {
  const abs = path.join(extractSlot(id), 'meta.json');
  if (!fs.existsSync(abs)) await mirrorFetch(abs);
  try { return JSON.parse(fs.readFileSync(abs, 'utf8')); } catch { return null; }
}

/** Restore the saved extraction into outDir for a build-only rerun. Returns
 *  the slot meta, or null when the slot is missing/incomplete. */
async function loadExtract(id, outDir) {
  const meta = await extractMeta(id);
  if (!meta) return null;
  fs.mkdirSync(outDir, { recursive: true });
  for (const f of EXTRACT_FILES) {
    const abs = path.join(extractSlot(id), f);
    if (!fs.existsSync(abs)) await mirrorFetch(abs);
    if (!fs.existsSync(abs)) {
      if (f === 'chase_messages.md') continue; // renderable without it
      return null;
    }
    fs.copyFileSync(abs, path.join(outDir, f));
  }
  return meta;
}

/** Archive a finished run: copy the OUT artifacts + results into the
 *  analysis's run dir and mirror everything to GCS. */
async function archiveRun(id, runId, outDir, results) {
  const dest = path.join(aRunDir(id, runId), 'out');
  fs.mkdirSync(dest, { recursive: true });
  for (const f of fs.readdirSync(outDir)) fs.copyFileSync(path.join(outDir, f), path.join(dest, f));
  fs.writeFileSync(path.join(aRunDir(id, runId), 'results.json'), JSON.stringify(results, null, 2));
  await mirrorUploadDir(aRunDir(id, runId));
}

/** Resolve a run artifact path, pulling it from the GCS mirror when the local
 *  copy is gone (fresh instance). */
async function runArtifact(id, runId, fileName) {
  const abs = path.join(aRunDir(id, runId), 'out', path.basename(fileName));
  if (!fs.existsSync(abs)) await mirrorFetch(abs);
  return abs;
}

async function runResults(id, runId) {
  const abs = path.join(aRunDir(id, runId), 'results.json');
  if (!fs.existsSync(abs)) await mirrorFetch(abs);
  try { return JSON.parse(fs.readFileSync(abs, 'utf8')); }
  catch { return null; }
}

/** Find which analysis a run belongs to (legacy routes address runs bare). */
function findRun(runId) {
  if (!fs.existsSync(ANALYSES)) return null;
  for (const id of fs.readdirSync(ANALYSES)) {
    if (fs.existsSync(aRunDir(id, runId))) return id;
  }
  return null;
}

// ---------------------------------------------------------------- migration
// Pre-analysis layout was dumps/<runId>/{out,results.json,files}. Wrap each
// legacy run into its own analysis (same id) so old runs stay reachable.
function migrateLegacy() {
  if (!fs.existsSync(DUMPS)) return;
  for (const id of fs.readdirSync(DUMPS)) {
    if (id === 'analyses' || id === '_staging' || !/^[a-f0-9]+$/.test(id)) continue;
    const legacy = path.join(DUMPS, id);
    if (!fs.existsSync(path.join(legacy, 'out', 'plan.json'))) continue;
    try {
      let name = 'Migrated run ' + id;
      try {
        const plan = JSON.parse(fs.readFileSync(path.join(legacy, 'out', 'plan.json'), 'utf8'));
        const v = (n) => (n && n.value != null ? n.value : null);
        name = `${v(plan.client) || 'Unknown client'} ${v(plan.job_number) || ''}`.trim();
      } catch { /* keep fallback name */ }
      const a = {
        id,
        name,
        auto_named: true,
        created_at: new Date().toISOString(),
        archived_at: null,
        last_run: { id, at: new Date().toISOString(), files_hash: null },
      };
      fs.mkdirSync(path.join(aRunDir(id, id)), { recursive: true });
      fs.renameSync(path.join(legacy, 'out'), path.join(aRunDir(id, id), 'out'));
      if (fs.existsSync(path.join(legacy, 'results.json'))) {
        fs.renameSync(path.join(legacy, 'results.json'), path.join(aRunDir(id, id), 'results.json'));
      }
      if (fs.existsSync(path.join(legacy, 'files'))) {
        fs.renameSync(path.join(legacy, 'files'), aFilesDir(id));
      }
      writeAnalysis(a);
      fs.rmSync(legacy, { recursive: true, force: true });
      console.log(`[greenlight] migrated legacy run ${id} -> analysis "${name}"`);
    } catch (e) {
      console.error(`[greenlight] legacy migration failed for ${id}:`, e.message);
    }
  }
}

fs.mkdirSync(ANALYSES, { recursive: true });
migrateLegacy();
bootSync();

module.exports = {
  DUMPS, ANALYSES, BUCKET,
  createAnalysis, listAnalyses, analysisDetail, renameAnalysis, recordRun,
  setArchived, deleteAnalysis, stageFile, removeFile, filesHash,
  ensureFiles, recordFileCount, localFileCount, recordSkipped, clearSkipped,
  archiveRun, runArtifact, runResults, findRun,
  saveExtract, loadExtract, extractMeta,
  aFilesDir, walk,
};
