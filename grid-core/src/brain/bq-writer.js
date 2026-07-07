/*
 * src/brain/bq-writer.js — Brain V3.5 BigQuery write.
 * ----------------------------------------------------------------------------
 * Lands a committed file's extracted rows into `client_<c>_historical.campaign_flights`,
 * mirroring the ingest/ pattern: ADC auth, region australia-southeast1, append load.
 *
 * Auth: Application Default Credentials (same as ingest/*). The identity running
 * the server needs roles/bigquery.jobUser (project) + dataEditor on the dataset.
 * The dataset itself must be pre-created by an admin (datasets.create is not part
 * of dataEditor) — writeSnapshot() reports dataset_missing rather than trying.
 *
 * Never throws to the caller — returns a status object so a BQ problem never
 * blocks the SQLite commit.
 */
'use strict';
const dbmod = require('./db');

const PROJECT = process.env.BRAIN_BQ_PROJECT || 'bidbrain-analytics';
const LOCATION = process.env.BRAIN_BQ_LOCATION || 'australia-southeast1';
const TABLE = 'campaign_flights';

// BQ table schema for a historical campaign flight (extracted row + provenance).
const SCHEMA = [
  { name: 'file_id', type: 'STRING' },
  { name: 'source_filename', type: 'STRING' },
  { name: 'client_id', type: 'STRING' },
  { name: 'campaign_name', type: 'STRING' },
  { name: 'channel', type: 'STRING' },
  { name: 'sub_channel', type: 'STRING' },
  { name: 'period_start', type: 'DATE' },
  { name: 'period_end', type: 'DATE' },
  { name: 'spend_aud', type: 'FLOAT' },
  { name: 'impressions', type: 'INTEGER' },
  { name: 'reach', type: 'INTEGER' },
  { name: 'clicks', type: 'INTEGER' },
  { name: 'conversions', type: 'INTEGER' },
  { name: 'grps', type: 'FLOAT' },
  { name: 'source_citation', type: 'STRING' },
  { name: 'confidence', type: 'FLOAT' },
  { name: 'committed_at', type: 'TIMESTAMP' }
];

let _bq = null;
function client() {
  if (_bq) return _bq;
  const { BigQuery } = require('@google-cloud/bigquery');
  _bq = new BigQuery({ projectId: PROJECT });
  return _bq;
}

function toDate(s) { return (s && /^\d{4}-\d{2}-\d{2}/.test(s)) ? s.slice(0, 10) : null; }
function toNum(n) { return (n == null || n === '') ? null : Number(n); }
function toInt(n) { const v = toNum(n); return v == null ? null : Math.round(v); }

// writeSnapshot(fileId) -> { written, dataset, table, rows?, reason?, error? }
async function writeSnapshot(fileId) {
  const file = dbmod.getFile(fileId);
  if (!file) return { written: false, reason: 'file_not_found' };
  const rows = dbmod.getExtractedRowsByFile(fileId);
  if (!rows.length) return { written: false, reason: 'no_rows' };

  const datasetId = 'client_' + file.client_id + '_historical';
  const committedAt = new Date().toISOString();
  const bqRows = rows.map(function (r) {
    return {
      file_id: r.file_id, source_filename: file.filename, client_id: r.client_id,
      campaign_name: r.campaign_name || null, channel: r.channel, sub_channel: r.sub_channel || null,
      period_start: toDate(r.period_start), period_end: toDate(r.period_end),
      spend_aud: toNum(r.spend_aud), impressions: toInt(r.impressions), reach: toInt(r.reach),
      clicks: toInt(r.clicks), conversions: toInt(r.conversions), grps: toNum(r.grps),
      source_citation: r.source_citation || null, confidence: toNum(r.confidence),
      committed_at: committedAt
    };
  });

  try {
    const bq = client();
    const dataset = bq.dataset(datasetId);
    const [dsExists] = await dataset.exists();
    if (!dsExists) {
      return { written: false, dataset: datasetId, table: TABLE, reason: 'dataset_missing',
        hint: 'Admin must create the dataset once: bq mk --location=' + LOCATION + ' --dataset ' + PROJECT + ':' + datasetId };
    }
    const table = dataset.table(TABLE);
    const [tExists] = await table.exists();
    if (!tExists) await table.create({ schema: SCHEMA, location: LOCATION });
    await table.insert(bqRows); // streaming insert; append-only
    return { written: true, dataset: datasetId, table: TABLE, rows: bqRows.length };
  } catch (e) {
    // PartialFailureError carries per-row detail
    const detail = (e && e.errors && e.errors[0] && JSON.stringify(e.errors[0].errors || e.errors[0])) || (e && e.message) || String(e);
    return { written: false, dataset: datasetId, table: TABLE, error: String(detail).slice(0, 400) };
  }
}

module.exports = { writeSnapshot, PROJECT, LOCATION, TABLE, SCHEMA };
