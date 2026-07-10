/*
 * src/brain/db.js — SQLite staging store for Brain V3 historical uploads.
 * ----------------------------------------------------------------------------
 * Uses better-sqlite3 (synchronous). DB file: grid-core/data/brain-historical.db
 * (gitignored). This is the V3 staging warehouse — the real BigQuery write is V3.5.
 */
'use strict';
const path = require('path');
const fs = require('fs');
const Database = require('better-sqlite3');

// On Cloud Run the app filesystem is ephemeral; point at /tmp via BRAIN_DATA_DIR.
const DATA_DIR = process.env.BRAIN_DATA_DIR || path.join(__dirname, '..', '..', 'data');
if (!fs.existsSync(DATA_DIR)) fs.mkdirSync(DATA_DIR, { recursive: true });
const DB_PATH = path.join(DATA_DIR, 'brain-historical.db');

const db = new Database(DB_PATH);
db.pragma('journal_mode = WAL');

db.exec(`
CREATE TABLE IF NOT EXISTS uploaded_files (
  id TEXT PRIMARY KEY, filename TEXT NOT NULL, file_type TEXT NOT NULL,
  size_bytes INTEGER NOT NULL, client_id TEXT NOT NULL, channel_hint TEXT,
  uploaded_at TEXT NOT NULL, local_path TEXT NOT NULL, status TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS parse_jobs (
  id TEXT PRIMARY KEY, file_id TEXT NOT NULL, started_at TEXT NOT NULL, finished_at TEXT,
  status TEXT NOT NULL, progress_pct INTEGER NOT NULL DEFAULT 0, overall_confidence REAL,
  llama_parse_raw TEXT, extraction_raw TEXT, verification_raw TEXT, error_message TEXT
);
CREATE TABLE IF NOT EXISTS extracted_rows (
  id TEXT PRIMARY KEY, job_id TEXT NOT NULL, file_id TEXT NOT NULL, client_id TEXT NOT NULL,
  campaign_name TEXT, channel TEXT NOT NULL, sub_channel TEXT,
  period_start TEXT NOT NULL, period_end TEXT NOT NULL,
  spend_aud REAL, impressions INTEGER, reach INTEGER, clicks INTEGER, conversions INTEGER, grps REAL,
  source_citation TEXT, confidence REAL NOT NULL,
  flagged_for_review INTEGER NOT NULL DEFAULT 0, user_edited INTEGER NOT NULL DEFAULT 0,
  committed INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS committed_snapshots (
  id TEXT PRIMARY KEY, committed_at TEXT NOT NULL, committed_by TEXT NOT NULL, client_id TEXT NOT NULL,
  file_id TEXT NOT NULL, row_count INTEGER NOT NULL, total_spend_aud REAL NOT NULL,
  earliest_period TEXT NOT NULL, latest_period TEXT NOT NULL,
  target_bq_dataset TEXT, target_bq_table TEXT
);
-- Central: per-field CONFIG overrides layered over config/central-seed.js. ONE store.
-- value is JSON-encoded so numbers/nulls/strings round-trip losslessly. source =
-- 'manual' (dropdown/inline edit) | 'plan' (committed from a media-plan extraction).
CREATE TABLE IF NOT EXISTS central_rows (
  row_id TEXT NOT NULL, field TEXT NOT NULL, value TEXT,
  updated_at TEXT NOT NULL, source TEXT NOT NULL DEFAULT 'manual',
  filename TEXT, cell_ref TEXT,
  PRIMARY KEY (row_id, field)
);
-- Central: media-plan extraction drafts. NEVER writes campaign rows directly —
-- pending -> human review -> commit (which writes central_rows).
CREATE TABLE IF NOT EXISTS plan_extractions (
  id TEXT PRIMARY KEY, filename TEXT NOT NULL, uploaded_at TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending', extracted_json TEXT,
  matched_row_id TEXT, user_id TEXT
);
`);

const now = () => new Date().toISOString();

// ---- Central field governance (single source of truth for what may be written) ----
// Fields the plan-reader commit may write (all [CONFIG] target fields).
const CENTRAL_PLAN_FIELDS = ['jobNumber', 'client', 'name', 'objective', 'channel', 'managedBy',
  'startDate', 'endDate', 'platformMargin', 'adServingCost', 'forecastCpm', 'keyKpi', 'kpiTarget',
  'budgetGross', 'totalBudget', 'spendMult', 'notes'];
// Fields the inline dropdown/edit route may write — the "manual-entry set": every
// [CONFIG] field a trader fills by hand (dropdowns + inline-editable cells). Still a
// strict whitelist; [CONFIG] identity/derived fields stay out (client/name/objective
// come from the plan-commit path, derived is never writable).
const CENTRAL_EDIT_FIELDS = ['managedBy', 'channel', 'status', 'platformMargin', 'jobNumber',
  'forecastCpm', 'keyKpi', 'totalBudget', 'budgetGross', 'startDate', 'endDate', 'adServingCost',
  'notes', 'spendMult'];
// DERIVED fields — never writable by anything. Any attempt is rejected (defense in depth).
const CENTRAL_DERIVED_FIELDS = ['campaignMargin', 'cpmPerformance', 'kpiPerformance', 'budgetRemaining',
  'pctBudgetSpent', 'pctFlightElapsed', 'pacingStatus', 'marginDelta', 'marginBand', 'health'];

module.exports = {
  db,
  DB_PATH,
  CENTRAL_PLAN_FIELDS,
  CENTRAL_EDIT_FIELDS,
  CENTRAL_DERIVED_FIELDS,

  createFile(f) {
    db.prepare(`INSERT INTO uploaded_files (id,filename,file_type,size_bytes,client_id,channel_hint,uploaded_at,local_path,status)
      VALUES (@id,@filename,@file_type,@size_bytes,@client_id,@channel_hint,@uploaded_at,@local_path,@status)`).run({
      channel_hint: null, uploaded_at: now(), status: 'uploaded', ...f
    });
    return this.getFile(f.id);
  },
  getFile(id) { return db.prepare('SELECT * FROM uploaded_files WHERE id=?').get(id); },
  updateFileStatus(id, status) { db.prepare('UPDATE uploaded_files SET status=? WHERE id=?').run(status, id); },

  createJob(fileId) {
    const id = 'job-' + fileId;
    db.prepare(`INSERT INTO parse_jobs (id,file_id,started_at,status,progress_pct) VALUES (?,?,?,?,0)`)
      .run(id, fileId, now(), 'queued');
    return id;
  },
  getJob(id) { return db.prepare('SELECT * FROM parse_jobs WHERE id=?').get(id); },
  getJobByFile(fileId) { return db.prepare('SELECT * FROM parse_jobs WHERE file_id=?').get(fileId); },
  updateJobProgress(id, status, pct) { db.prepare('UPDATE parse_jobs SET status=?, progress_pct=? WHERE id=?').run(status, pct, id); },
  updateJobRaw(id, field, value) {
    if (!['llama_parse_raw', 'extraction_raw', 'verification_raw'].includes(field)) return;
    db.prepare(`UPDATE parse_jobs SET ${field}=? WHERE id=?`).run(value, id);
  },
  updateJobResult(id, patch) {
    const cols = Object.keys(patch);
    db.prepare(`UPDATE parse_jobs SET ${cols.map(c => c + '=@' + c).join(', ')} WHERE id=@id`).run({ id, ...patch });
  },

  insertExtractedRows(rows) {
    const stmt = db.prepare(`INSERT INTO extracted_rows
      (id,job_id,file_id,client_id,campaign_name,channel,sub_channel,period_start,period_end,
       spend_aud,impressions,reach,clicks,conversions,grps,source_citation,confidence,flagged_for_review)
      VALUES (@id,@job_id,@file_id,@client_id,@campaign_name,@channel,@sub_channel,@period_start,@period_end,
       @spend_aud,@impressions,@reach,@clicks,@conversions,@grps,@source_citation,@confidence,@flagged_for_review)`);
    const tx = db.transaction((rs) => rs.forEach(r => stmt.run(r)));
    tx(rows);
  },
  getExtractedRowsByFile(fileId) { return db.prepare('SELECT * FROM extracted_rows WHERE file_id=? ORDER BY period_start, channel').all(fileId); },
  getRow(id) { return db.prepare('SELECT * FROM extracted_rows WHERE id=?').get(id); },
  updateExtractedRow(id, patch) {
    const allowed = ['campaign_name', 'channel', 'sub_channel', 'period_start', 'period_end', 'spend_aud', 'impressions', 'reach', 'clicks', 'conversions', 'grps'];
    const cols = Object.keys(patch).filter(k => allowed.includes(k));
    if (!cols.length) return this.getRow(id);
    db.prepare(`UPDATE extracted_rows SET ${cols.map(c => c + '=@' + c).join(', ')}, user_edited=1 WHERE id=@id`).run({ id, ...patch });
    return this.getRow(id);
  },

  commitSnapshot(fileId, committedBy) {
    const file = this.getFile(fileId);
    const rows = this.getExtractedRowsByFile(fileId);
    if (!file || !rows.length) return null;
    const totalSpend = rows.reduce((a, r) => a + (r.spend_aud || 0), 0);
    const periods = rows.map(r => r.period_start).concat(rows.map(r => r.period_end)).sort();
    const snap = {
      id: 'snap-' + fileId, committed_at: now(), committed_by: committedBy || 'unknown',
      client_id: file.client_id, file_id: fileId, row_count: rows.length,
      total_spend_aud: Math.round(totalSpend * 100) / 100,
      earliest_period: periods[0], latest_period: periods[periods.length - 1],
      target_bq_dataset: 'client_' + file.client_id + '_historical', target_bq_table: 'campaign_flights'
    };
    db.prepare(`INSERT OR REPLACE INTO committed_snapshots
      (id,committed_at,committed_by,client_id,file_id,row_count,total_spend_aud,earliest_period,latest_period,target_bq_dataset,target_bq_table)
      VALUES (@id,@committed_at,@committed_by,@client_id,@file_id,@row_count,@total_spend_aud,@earliest_period,@latest_period,@target_bq_dataset,@target_bq_table)`).run(snap);
    db.prepare('UPDATE extracted_rows SET committed=1 WHERE file_id=?').run(fileId);
    this.updateFileStatus(fileId, 'committed');
    return snap;
  },

  getRecentUploads(clientId) {
    const files = clientId
      ? db.prepare('SELECT * FROM uploaded_files WHERE client_id=? ORDER BY uploaded_at DESC').all(clientId)
      : db.prepare('SELECT * FROM uploaded_files ORDER BY uploaded_at DESC').all();
    return files.map(f => {
      const job = this.getJobByFile(f.id);
      const rows = this.getExtractedRowsByFile(f.id);
      const periods = rows.map(r => r.period_start).concat(rows.map(r => r.period_end)).filter(Boolean).sort();
      return {
        ...f,
        row_count: rows.length,
        flagged_row_count: rows.filter(r => r.flagged_for_review).length,
        confidence: job ? job.overall_confidence : null,
        date_range: periods.length ? { start: periods[0], end: periods[periods.length - 1] } : null,
        channels: [...new Set(rows.map(r => r.channel))]
      };
    });
  },

  // ==================== Central: CONFIG overrides (central_rows) ====================
  // value is JSON-encoded on the way in and parsed on the way out.
  _decodeVal(v) { if (v == null) return null; try { return JSON.parse(v); } catch { return v; } },

  // Whether a field may be written by a given route. Returns {ok} or {ok:false, error}.
  centralFieldAllowed(field, scope) {
    if (CENTRAL_DERIVED_FIELDS.includes(field)) return { ok: false, error: `'${field}' is a DERIVED field and can never be edited` };
    const list = scope === 'plan' ? CENTRAL_PLAN_FIELDS : CENTRAL_EDIT_FIELDS;
    if (!list.includes(field)) return { ok: false, error: `'${field}' is not an editable CONFIG field` };
    return { ok: true };
  },

  // All overrides, grouped by row_id: { rowId: { field: {value, source, filename, cellRef, updatedAt} } }
  getCentralOverrides() {
    const rows = db.prepare('SELECT * FROM central_rows').all();
    const out = {};
    for (const r of rows) {
      (out[r.row_id] || (out[r.row_id] = {}))[r.field] = {
        value: this._decodeVal(r.value), source: r.source, filename: r.filename || null,
        cellRef: r.cell_ref || null, updatedAt: r.updated_at
      };
    }
    return out;
  },
  // Flat {field: value} for one row (used server-side for conflict detection).
  getCentralFieldsForId(rowId) {
    const rows = db.prepare('SELECT field, value FROM central_rows WHERE row_id=?').all(rowId);
    const out = {}; rows.forEach(r => { out[r.field] = this._decodeVal(r.value); });
    return out;
  },
  // Write ONE field. Enforces the whitelist for `scope` ('edit' | 'plan'). Returns {ok,error?}.
  setCentralField(rowId, field, value, scope, meta) {
    const chk = this.centralFieldAllowed(field, scope);
    if (!chk.ok) return chk;
    meta = meta || {};
    db.prepare(`INSERT INTO central_rows (row_id,field,value,updated_at,source,filename,cell_ref)
      VALUES (@row_id,@field,@value,@updated_at,@source,@filename,@cell_ref)
      ON CONFLICT(row_id,field) DO UPDATE SET value=@value,updated_at=@updated_at,source=@source,filename=@filename,cell_ref=@cell_ref`)
      .run({
        row_id: rowId, field, value: JSON.stringify(value === undefined ? null : value),
        updated_at: now(), source: meta.source || (scope === 'plan' ? 'plan' : 'manual'),
        filename: meta.filename || null, cell_ref: meta.cellRef || null
      });
    return { ok: true };
  },

  // ==================== Central: plan extraction drafts (plan_extractions) ==========
  createPlanExtraction(rec) {
    db.prepare(`INSERT INTO plan_extractions (id,filename,uploaded_at,status,extracted_json,matched_row_id,user_id)
      VALUES (@id,@filename,@uploaded_at,@status,@extracted_json,@matched_row_id,@user_id)`).run({
      status: 'pending', extracted_json: null, matched_row_id: null, user_id: null,
      uploaded_at: now(), ...rec
    });
    return this.getPlanExtraction(rec.id);
  },
  getPlanExtraction(id) { return db.prepare('SELECT * FROM plan_extractions WHERE id=?').get(id); },
  setPlanStatus(id, status, matchedRowId) {
    if (matchedRowId !== undefined) db.prepare('UPDATE plan_extractions SET status=?, matched_row_id=? WHERE id=?').run(status, matchedRowId, id);
    else db.prepare('UPDATE plan_extractions SET status=? WHERE id=?').run(status, id);
  }
};
