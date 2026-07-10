/*
 * src/brain/db.js — SQLite staging store for Brain V3 historical uploads.
 * ----------------------------------------------------------------------------
 * Uses better-sqlite3 (synchronous). DB file: grid-core/data/brain-historical.db
 * (gitignored). This is the V3 staging warehouse — the real BigQuery write is V3.5.
 */
'use strict';
const path = require('path');
const fs = require('fs');
const crypto = require('crypto');
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
-- pending -> human review -> commit (which writes campaigns + central_rows).
CREATE TABLE IF NOT EXISTS plan_extractions (
  id TEXT PRIMARY KEY, filename TEXT NOT NULL, uploaded_at TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending', extracted_json TEXT,
  matched_row_id TEXT, user_id TEXT
);
-- Central: the SOURCE OF TRUTH for campaign rows (replaces reading the baked DATA
-- literal). Columns are calc.js CONFIG + API fields. Soft-delete only via archivedAt.
CREATE TABLE IF NOT EXISTS campaigns (
  id TEXT PRIMARY KEY,
  section TEXT, client TEXT, name TEXT,
  currency TEXT, jobNumber TEXT, objective TEXT, channel TEXT, managedBy TEXT, status TEXT,
  startDate TEXT, endDate TEXT,
  platformMargin REAL, adServing TEXT, adServingCost REAL, forecastCpm REAL,
  keyKpi TEXT, kpiTarget REAL, budgetGross REAL, totalBudget REAL, spendMult REAL,
  campaignLink TEXT, nextReportingDue TEXT, notes TEXT,
  impressions REAL, mediaSpend REAL, clientSpend REAL,
  metricsSource TEXT, lastSyncedAt TEXT,
  createdAt TEXT NOT NULL, updatedAt TEXT NOT NULL, archivedAt TEXT, sourceOfRecord TEXT NOT NULL
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
  },

  // ==================== Central: campaigns (SOURCE OF TRUTH) ========================
  _CAMPAIGN_CONFIG_COLS: ['section', 'client', 'name', 'currency', 'jobNumber', 'objective', 'channel',
    'managedBy', 'status', 'startDate', 'endDate', 'platformMargin', 'adServing', 'adServingCost',
    'forecastCpm', 'keyKpi', 'kpiTarget', 'budgetGross', 'totalBudget', 'spendMult', 'campaignLink',
    'nextReportingDue', 'notes'],
  _CAMPAIGN_ALL_COLS: null,   // filled below

  _genCampaignId() { return 'cmp-' + crypto.randomBytes(6).toString('hex'); },

  // ONE-TIME import of the sheet parse (calc-shaped rows). Idempotency = an
  // import-once GUARD: if any sheet-import row already exists, do nothing (return
  // alreadyImported). NOTE: (section,client,name) is NOT unique in the sheet — a
  // campaign repeats that triple across channels (e.g. "Always On" on Google/Meta/
  // TradeDesk), so a per-row natural-key dedup would silently DROP real rows. The
  // guard is lossless and idempotent. Blank name→null (needs-input); blank status→Draft.
  importCentralSnapshot(rows, opts) {
    const force = opts && opts.force;
    const already = db.prepare("SELECT COUNT(*) n FROM campaigns WHERE sourceOfRecord='sheet-import'").get().n;
    if (already > 0 && !force) {
      return { inserted: 0, skipped: rows.length, alreadyImported: true, total: db.prepare('SELECT COUNT(*) n FROM campaigns').get().n, byStatus: {} };
    }
    const cfg = this._CAMPAIGN_CONFIG_COLS;
    const insert = db.prepare(`INSERT INTO campaigns (${this._CAMPAIGN_ALL_COLS.join(',')})
      VALUES (${this._CAMPAIGN_ALL_COLS.map(c => '@' + c).join(',')})`);
    let inserted = 0; const byStatus = {};
    const tx = db.transaction((rs) => {
      for (const row of rs) {
        const rec = {}; this._CAMPAIGN_ALL_COLS.forEach(c => { rec[c] = null; });
        cfg.forEach(c => { if (row[c] !== undefined) rec[c] = row[c]; });
        rec.section = row.section != null ? row.section : (row.agency != null ? row.agency : null);
        rec.client = row.client != null ? row.client : null;
        rec.name = (row.name == null || row.name === '') ? null : row.name;
        rec.status = (row.status == null || row.status === '') ? 'Draft' : row.status;
        rec.impressions = row.impressions != null ? row.impressions : null;
        rec.mediaSpend = row.mediaSpend != null ? row.mediaSpend : null;
        rec.clientSpend = row.clientSpend != null ? row.clientSpend : null;
        rec.metricsSource = 'sheet-import'; rec.lastSyncedAt = null;
        rec.id = this._genCampaignId(); rec.createdAt = now(); rec.updatedAt = now();
        rec.archivedAt = null; rec.sourceOfRecord = 'sheet-import';
        insert.run(rec); inserted++;
        byStatus[rec.status] = (byStatus[rec.status] || 0) + 1;
      }
    });
    tx(rows);
    return { inserted, skipped: 0, total: db.prepare('SELECT COUNT(*) n FROM campaigns').get().n, byStatus };
  },

  getCampaigns() { return db.prepare('SELECT * FROM campaigns ORDER BY section, client, name').all(); },
  getCampaign(id) { return db.prepare('SELECT * FROM campaigns WHERE id=?').get(id); },

  // Create a thin campaign (Add button / plan create-new). section+client+name required;
  // derived rejected; status defaults to 'Draft'. Returns {ok,campaign} or {ok:false,error}.
  createCampaign(input, sourceOfRecord) {
    if (!input || !input.section || !input.client || !input.name) return { ok: false, error: 'section, client and name are required' };
    for (const k in input) if (CENTRAL_DERIVED_FIELDS.includes(k)) return { ok: false, error: `'${k}' is a DERIVED field and cannot be set` };
    const rec = {}; this._CAMPAIGN_ALL_COLS.forEach(c => { rec[c] = null; });
    this._CAMPAIGN_CONFIG_COLS.forEach(c => { if (input[c] !== undefined) rec[c] = input[c]; });
    rec.id = this._genCampaignId(); rec.status = input.status || 'Draft';
    rec.metricsSource = 'sheet-import'; rec.lastSyncedAt = null;
    rec.createdAt = now(); rec.updatedAt = now(); rec.archivedAt = null;
    rec.sourceOfRecord = sourceOfRecord || 'manual';
    db.prepare(`INSERT INTO campaigns (${this._CAMPAIGN_ALL_COLS.join(',')}) VALUES (${this._CAMPAIGN_ALL_COLS.map(c => '@' + c).join(',')})`).run(rec);
    return { ok: true, campaign: this.getCampaign(rec.id) };
  },

  // Write ONE CONFIG field on a campaign (source of truth) AND append provenance to
  // central_rows. Whitelisted per scope; DERIVED always rejected. field is validated
  // against the whitelist before it is ever interpolated into SQL.
  updateCampaignField(id, field, value, scope, meta) {
    const chk = this.centralFieldAllowed(field, scope);
    if (!chk.ok) return chk;
    const cur = this.getCampaign(id);
    if (!cur) return { ok: false, error: 'campaign not found' };
    db.prepare(`UPDATE campaigns SET ${field}=@value, updatedAt=@t WHERE id=@id`).run({ value: value === undefined ? null : value, t: now(), id });
    this.setCentralField(id, field, value, scope, meta);   // provenance (central_rows, row_id=campaign id)
    return { ok: true, campaign: this.getCampaign(id) };
  },

  // Soft delete — hidden except the Archived chip. No hard-delete method exists.
  archiveCampaign(id) {
    const cur = this.getCampaign(id);
    if (!cur) return { ok: false, error: 'campaign not found' };
    db.prepare('UPDATE campaigns SET archivedAt=@t, updatedAt=@t WHERE id=@id').run({ t: now(), id });
    return { ok: true, campaign: this.getCampaign(id) };
  }
};
module.exports._CAMPAIGN_ALL_COLS = ['id'].concat(module.exports._CAMPAIGN_CONFIG_COLS)
  .concat(['impressions', 'mediaSpend', 'clientSpend', 'metricsSource', 'lastSyncedAt',
    'createdAt', 'updatedAt', 'archivedAt', 'sourceOfRecord']);
