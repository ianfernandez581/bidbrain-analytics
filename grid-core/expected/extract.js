// Stage 2 - extraction. Deterministic preprocess, then ONE Claude API call
// with a structured schema, then the generic code validator. Writes into out/:
//   manifest.json, plan.json, findings.json, messages.json, chase_messages.md
// Client-agnostic: nothing in this file names a client, a job, or a number.
//
// Rules enforced by prompt + schema: every value cites its source (file >
// sheet > row/cell where possible); missing or unresolvably conflicting =
// null plus a finding, never a guess. Judgement findings and chase drafts are
// model work, tagged origin "model"; all arithmetic checks run in validate.js.
//
// Usage: node extract.js [--files <dir>]   (default dir: ../files)
// Env: ANTHROPIC_API_KEY (or grid-core/.env), EXPECTED_MODEL (default claude-opus-5).
// GREENLIGHT_API_KEY / GREENLIGHT_BASE_URL, when set, override the ANTHROPIC_*
// pair for THIS stage only - lets Greenlight run on a different Claude-compatible
// provider (e.g. Kimi) without moving the rest of the grid's model calls.
'use strict';

const fs = require('fs');
const path = require('path');
const { preprocess } = require('./preprocess');
const { validate } = require('./validate');

const ROOT = __dirname;
const OUT = process.env.GREENLIGHT_OUT_DIR || path.join(ROOT, 'out');
let MODEL = process.env.EXPECTED_MODEL || 'claude-opus-5'; // re-resolved in main() after loadDotEnv

// ---- minimal .env loader (repo has no dotenv; grid-core/.env is gitignored)
function loadDotEnv() {
  if (process.env.ANTHROPIC_API_KEY) return;
  const envPath = path.join(ROOT, '..', '.env');
  if (!fs.existsSync(envPath)) return;
  for (const line of fs.readFileSync(envPath, 'utf8').split(/\r?\n/)) {
    const m = /^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)\s*$/.exec(line);
    if (m && !process.env[m[1]]) process.env[m[1]] = m[2].replace(/^["']|["']$/g, '');
  }
}

// ---- schema helpers. The structured-outputs compiler caps union-typed
// parameters (nullable type arrays) at 16, so this schema uses NO unions:
// every field is a plain string, "" means missing/unknown, and numeric fields
// are numeric STRINGS. normalizePlan() converts back to nulls and numbers.
const obj = (props) => ({ type: 'object', properties: props, required: Object.keys(props), additionalProperties: false });
const arr = (items) => ({ type: 'array', items });
const str = { type: 'string' };

const CITED = obj({ value: str, source: str });
const DATE_FIELD = obj({ value: str, candidates: arr(str), resolution_rationale: str });

const SCHEMA = obj({
  plan: obj({
    client: CITED,
    job_number: CITED,
    campaign_name: CITED,
    identification_confidence: { type: 'string', enum: ['high', 'medium', 'low'] },
    currency: CITED,
    total_budget: CITED,
    fee_treatment: CITED,
    flight_start: DATE_FIELD,
    flight_end: DATE_FIELD,
    stated_duration_days: CITED,
    campaigns: arr(obj({
      campaign_name: str,
      platform: str,
      budget: str,
      rate_type: str,
      rate_value: str,
      goal_impressions: str,
      goal_clicks: str,
      goal_ctr: str,
      start: str,
      end: str,
      source: str,
    })),
    platform_campaign_rows: arr(str),
    platform_campaigns_claimed_total: CITED,
    urls: arr(str),
    approval_records: arr(str),
    referenced_files: arr(str),
  }),
  judgement_findings: arr(str),
  chase_messages: arr(obj({ recipient: str, title: str, body: str })),
});

const SYSTEM = `You are the extraction engine for the Expected side of The Grid, a media agency's campaign pacing system. You receive a converted dump of a media buyer's campaign files (media plans, briefs/activation forms, platform setup sheets, creative sheets, trackers, bulk uploads) plus a file inventory with media metadata measured in code. You output one structured record.

HARD RULES
- Every extracted value cites its source: file, then sheet and row (the sheets are row-numbered R1, R2, ...). No citation, no value.
- Missing stays missing: a field with no source is null. NEVER invent, infer, or default a value. A confidently wrong number is worse than a gap.
- Conflicting values: list every candidate with its source. Set the resolved value ONLY when the documents themselves resolve it (later documents are unanimous, or the earlier document carries its own revision annotation); explain in resolution_rationale. If no documented resolution exists, value stays null.
- Do no arithmetic. Code reconciles sums, dates, and rates after you. Your job is faithful extraction plus judgement.
- If the dump might contain two different clients or campaigns conflated, set identification_confidence to low and emit a blocker finding: merging two clients' data is the worst failure this system can produce.
- Dates are ISO YYYY-MM-DD. Use "-" only, never em or en dashes, anywhere in any text you produce.
- OUTPUT CONVENTIONS (the schema has no nulls): an empty string "" means missing/unknown - use it for any value, source, date, or status you cannot ground in a document. Numeric values (budgets, totals, impressions, clicks, rates, CTRs, durations) are numeric STRINGS with no symbols or thousands separators, e.g. "35000", "18", "0.004". Every source string has the form: FILE | LOCATION, e.g. "media_plan.xlsx | sheet 'Media Plan', row 8". A campaign line's single source covers all its numbers (they come from one plan row).
- PIPE-DELIMITED LIST FORMATS (one string per entry, fields separated by " | ", "" for an unknown field, the LAST field may itself contain pipes):
  - flight candidates: VALUE | NOTE | SOURCE  (e.g. "2026-06-01 | all 12 setup rows agree | setup.xlsx | sheet 'Grid', rows 4-15")
  - platform_campaign_rows: NAME | PLATFORM | BUDGET | START | END | GEO
  - urls: PLATFORM | GEO | CONTEXT | URL  (URL last so its query string never breaks the format)
  - approval_records: SCOPE | STATUS | SOURCE  (STATUS "" means the approval field exists but nothing is recorded)
  - judgement_findings: SEVERITY | STAGE | CHIP | TITLE | DETAIL | SOURCE  (SEVERITY one of blocker/missing/gap/inconsistent/watch/housekeeping; STAGE one of Request Received/Media Plan Approved/Raw Materials Complete/Campaign Built/Live/Pacing; CHIP a short uppercase label)

FIELD GUIDANCE
- campaigns: the media plan's budget lines, the pacing grain - one entry per plan line that carries its own budget, cost rate, and volume goals (impressions/clicks). Do NOT put platform build rows here. campaign_name must be TRACEABLE on its own: use the line's full printed name, and when the printed label is a bare funnel stage or audience (e.g. "Awareness"), qualify it with the campaign/programme name and channel from the same sheet (e.g. "ECAA - Awareness (LinkedIn)") so each entry maps unambiguously to one platform campaign. Never emit two entries with the same name.
- platform_campaigns.rows: the platform-level build rows (e.g. each LinkedIn campaign in a setup grid) with their individual budgets and dates. claimed_total: if the sheet carrying those rows has a TOTAL row or label claiming a total for them, extract that claimed number with its citation - even if you suspect it is wrong. Code checks whether it sums.
- urls: every distinct destination, clickthrough, and confirmation URL in the dump, with the platform it serves on, the market geo as a 2-letter code where determinable, and a short context label.
- approval_records: every approval, sign-off, go-live status, or install-confirmation field you find - one entry per scope (e.g. "media plan sign-off", "doc ads creative", "statics and video creative", "tracking tag install test"). status is the recorded value, or null when the field exists but nothing is recorded. Missing sign-off for the plan itself belongs here too (status null, source "absent from all supplied files").
- referenced_files: every asset file NAME any document references (creative file names, PDFs in bulk uploads or trackers), so code can flag files present in the dump that nothing references.

JUDGEMENT FINDINGS (yours; code handles all arithmetic)
Flag what a careful media operations lead would flag but arithmetic cannot catch: expectation gaps between what a brief states and what the plan contracts (budget figures, KPI framing such as leads-vs-impressions); scope that changed between document versions with no recorded decision; documents whose printed values were superseded but never re-issued; sheets in a workbook that belong to a different campaign; installs or tests that were instructed but never confirmed. Severity: blocker = a stage's defining artifact is missing or the campaign cannot be trusted to launch/reconcile; gap = stated expectation contradicts an agreed one; missing/inconsistent/watch/housekeeping as they read. Assign each to the stage where it bites.

CHASE MESSAGES
Draft one message per recipient, consolidating everything that recipient owes (typically: one to the client contact, one internal to the media team). Tone rules: warm opener naming the campaign; acknowledge what has already been received; the specific list of what is needed with exact specifications; why it matters framed as impact on their campaign; a clear date derived from real arithmetic (flight end, wash-up), never an invented deadline; an offer of help. Never assign blame - no "as previously requested", no "still waiting". Short paragraphs a person can act on from a phone. Plain text, no markdown headers inside the body.`;

function sanitize(x) {
  if (typeof x === 'string') return x.replace(/[\u2013\u2014]/g, '-');
  if (Array.isArray(x)) return x.map(sanitize);
  if (x && typeof x === 'object') {
    const o = {};
    for (const k of Object.keys(x)) o[k] = sanitize(x[k]);
    return o;
  }
  return x;
}

// ---- normalization: the schema uses "" sentinels and numeric strings (no
// unions allowed); downstream contract is real nulls and numbers.
const normStr = (s) => (s == null || s === '' ? null : s);
const normNum = (s) => {
  if (s == null || s === '') return null;
  const n = Number(String(s).replace(/[, ]/g, ''));
  return Number.isFinite(n) ? n : null;
};
const parseSource = (s) => {
  const t = normStr(s);
  if (!t) return null;
  const i = t.indexOf('|');
  if (i < 0) return { file: t.trim(), location: null };
  return { file: t.slice(0, i).trim(), location: normStr(t.slice(i + 1).trim()) };
};
// Split a pipe-delimited entry into exactly n fields; the last field keeps
// any remaining pipes (URLs, sources with sheet locations).
const splitPipes = (s, n) => {
  const parts = String(s).split('|').map((x) => x.trim());
  if (parts.length <= n) return [...parts, ...Array(n - parts.length).fill('')];
  return [...parts.slice(0, n - 1), parts.slice(n - 1).join(' | ')];
};
const normCited = (node, numeric) => ({
  value: node ? (numeric ? normNum(node.value) : normStr(node.value)) : null,
  citation: node ? parseSource(node.source) : null,
});
const normDate = (f) => ({
  value: f ? normStr(f.value) : null,
  candidates: ((f && f.candidates) || []).map((line) => {
    const [value, note, source] = splitPipes(line, 3);
    const cit = parseSource(source);
    return { value: normStr(value), file: cit ? cit.file : null, location: cit ? cit.location : null, note: normStr(note) };
  }).filter((c) => c.value),
  resolution_rationale: f ? normStr(f.resolution_rationale) : null,
});

function normalizePlan(p) {
  const pc = p.platform_campaigns || {};
  return {
    client: normCited(p.client),
    job_number: normCited(p.job_number),
    campaign_name: normCited(p.campaign_name),
    identification_confidence: p.identification_confidence,
    currency: normCited(p.currency),
    total_budget: normCited(p.total_budget, true),
    fee_treatment: normCited(p.fee_treatment),
    flight_start: normDate(p.flight_start),
    flight_end: normDate(p.flight_end),
    stated_duration_days: normCited(p.stated_duration_days, true),
    campaigns: (p.campaigns || []).map((c) => {
      const cit = parseSource(c.source);
      const cited = (v, numeric) => ({ value: numeric ? normNum(v) : normStr(v), citation: cit });
      return {
        campaign_name: c.campaign_name,
        platform: normStr(c.platform),
        budget: cited(c.budget, true),
        rate_type: normStr(c.rate_type),
        rate_value: cited(c.rate_value, true),
        goal_impressions: cited(c.goal_impressions, true),
        goal_clicks: cited(c.goal_clicks, true),
        goal_ctr: normNum(c.goal_ctr),
        start: normStr(c.start),
        end: normStr(c.end),
      };
    }),
    platform_campaigns: {
      rows: (p.platform_campaign_rows || []).map((line) => {
        const [name, platform, budget, start, end, geo] = splitPipes(line, 6);
        return { name: normStr(name), platform: normStr(platform), budget: normNum(budget), start: normStr(start), end: normStr(end), geo: normStr(geo) };
      }).filter((r) => r.name),
      claimed_total: normCited(p.platform_campaigns_claimed_total, true),
    },
    urls: (p.urls || []).map((line) => {
      const [platform, geo, context, url] = splitPipes(line, 4);
      return { url: normStr(url), platform: normStr(platform), geo: normStr(geo), context: normStr(context) || 'url' };
    }).filter((u) => u.url),
    approval_records: (p.approval_records || []).map((line) => {
      const [scope, status, source] = splitPipes(line, 3);
      return { scope: normStr(scope), status: normStr(status), source: normStr(source) };
    }).filter((a) => a.scope),
    referenced_files: p.referenced_files || [],
    notes: [],
  };
}

// ---- campaign identity guard (deterministic, multi-campaign safety).
// Job numbers ride 4-digit filename prefixes (2053_SE_..., 2279_...). If the
// dump partitions across more than one job, never blend: keep the majority
// job's campaigns, emit a blocker listing which files belong to which job,
// and stamp plan.identity_guard so the UI can warn prominently.
function identityGuard(manifest, plan) {
  const jobs = new Map();
  for (const f of manifest.files) {
    const base = f.file.split('/').pop();
    const m = /^(\d{4})[_\s-]/.exec(base);
    if (!m) continue;
    if (!jobs.has(m[1])) jobs.set(m[1], []);
    jobs.get(m[1]).push(f.file);
  }
  if (jobs.size <= 1) return null;
  const sorted = [...jobs.entries()].sort((a, b) => b[1].length - a[1].length);
  const majority = sorted[0][0];
  const counts = sorted.map(([j, fl]) => `${j} (${fl.length} file${fl.length === 1 ? '' : 's'})`).join(', ');
  return {
    majority,
    jobs: Object.fromEntries(sorted),
    message: `This dump appears to contain files from multiple campaigns: ${counts}. Analysis ran on ${majority} only. Remove or re-upload the others separately.`,
  };
}

function applyIdentityGuard(guard, plan) {
  plan.identity_guard = guard;
  // Keep only campaigns whose citation traces to a majority-job file (or to a
  // file carrying no job prefix, e.g. an unprefixed media plan).
  plan.campaigns = (plan.campaigns || []).filter((c) => {
    const file = (c.budget && c.budget.citation && c.budget.citation.file) || '';
    const m = /^(\d{4})[_\s-]/.exec(file.split('/').pop());
    return !m || m[1] === guard.majority;
  });
  return {
    id: 'guard_multi_job',
    severity: 'blocker',
    stage: 'Request Received',
    chip: 'MULTIPLE CAMPAIGNS',
    title: `Dump contains files from ${Object.keys(guard.jobs).length} different campaigns - not blended`,
    detail: guard.message + ' Files by job: ' + Object.entries(guard.jobs).map(([j, fl]) => `${j}: ${fl.join(', ')}`).join(' ;; '),
    source: 'file inventory (4-digit job prefixes)',
    origin: 'code',
  };
}

const SEVERITIES = ['blocker', 'missing', 'gap', 'inconsistent', 'watch', 'housekeeping'];
const STAGES = ['Request Received', 'Media Plan Approved', 'Raw Materials Complete', 'Campaign Built', 'Live', 'Pacing'];
function parseFindings(lines) {
  return (lines || []).map((line) => {
    const [severity, stage, chip, title, detail, source] = splitPipes(line, 6);
    if (!title) return null;
    return {
      severity: SEVERITIES.includes((severity || '').toLowerCase()) ? severity.toLowerCase() : 'watch',
      stage: STAGES.includes(stage) ? stage : 'Media Plan Approved',
      chip: (chip || 'NOTE').toUpperCase(),
      title, detail: detail || '', source: source || '',
    };
  }).filter(Boolean);
}

async function callClaude(client, bundleText) {
  const base = {
    model: MODEL,
    max_tokens: 64000,
    output_config: { format: { type: 'json_schema', schema: SCHEMA } },
    system: SYSTEM,
    messages: [{
      role: 'user',
      content: [{ type: 'text', text: `Extract the campaign record from this dump.\n\n${bundleText}` }],
    }],
  };
  let msg;
  try {
    // Preferred: with server-side refusal fallback (skill-recommended default).
    const stream = client.beta.messages.stream({
      ...base,
      betas: ['server-side-fallback-2026-07-01'],
      fallbacks: 'default',
    });
    msg = await stream.finalMessage();
  } catch (e) {
    // If the fallback beta is rejected in this environment, retry plain.
    const s = String(e && e.message || e);
    if (!/fallback|beta/i.test(s)) throw e;
    console.log('[extract] fallback beta rejected here, retrying without it');
    const stream = client.messages.stream(base);
    msg = await stream.finalMessage();
  }
  if (msg.stop_reason === 'refusal') {
    throw new Error('the model declined this request (stop_reason refusal)' +
      (msg.stop_details && msg.stop_details.category ? `, category ${msg.stop_details.category}` : ''));
  }
  const text = msg.content.find((b) => b.type === 'text');
  if (!text) throw new Error(`no text block in response (stop_reason ${msg.stop_reason})`);
  const usage = msg.usage || {};
  console.log(`[extract] model ${msg.model} in=${usage.input_tokens} out=${usage.output_tokens}`);
  return JSON.parse(text.text);
}

function renderChaseMd(messages) {
  const parts = ['# Chase messages\n\nDrafts only. A person reviews and sends. AI-authored per run.\n'];
  for (const m of messages) {
    parts.push(`---\n\n## ${m.title}\n\nRecipient: ${m.recipient}\n\n${m.body}\n`);
  }
  return parts.join('\n');
}

async function main() {
  const argIdx = process.argv.indexOf('--files');
  const filesDir = argIdx > -1 ? process.argv[argIdx + 1] : path.join(ROOT, '..', 'files');
  loadDotEnv();
  MODEL = process.env.EXPECTED_MODEL || MODEL; // .env may have supplied it just now
  if (!process.env.GREENLIGHT_API_KEY && !process.env.ANTHROPIC_API_KEY) {
    console.error('[extract] BLOCKED: no GREENLIGHT_API_KEY or ANTHROPIC_API_KEY in the environment or grid-core/.env');
    process.exit(2);
  }

  fs.mkdirSync(OUT, { recursive: true });
  console.log(`[extract] preprocessing ${filesDir}`);
  const { manifest, bundleText } = preprocess(filesDir);
  fs.writeFileSync(path.join(OUT, 'manifest.json'), JSON.stringify(manifest, null, 2));
  console.log(`[stage] preprocess-done files=${manifest.files.length} bundle_chars=${bundleText.length}`);

  const Anthropic = require('@anthropic-ai/sdk');
  // Generous retries: this is one large request (~125K input tokens), so a
  // tier rate-limit window needs patience, not a fast fail. The SDK honors
  // retry-after on 429 and backs off on 5xx/529.
  // GREENLIGHT_* wins over ANTHROPIC_* so this stage can bill a different
  // provider (Kimi subscription) while Brain/plan-reader keep the Anthropic key.
  const client = new Anthropic({
    maxRetries: 6,
    apiKey: process.env.GREENLIGHT_API_KEY || process.env.ANTHROPIC_API_KEY,
    baseURL: process.env.GREENLIGHT_BASE_URL || process.env.ANTHROPIC_BASE_URL || undefined,
  });
  console.log(`[stage] model-start model=${MODEL}`);
  const raw = await callClaude(client, bundleText);
  const result = sanitize(raw);
  console.log('[stage] model-done');

  const plan = normalizePlan(result.plan);
  plan.extractor = { model: MODEL, generated_at: new Date().toISOString(), dump_dir: filesDir, one_call: true };
  const guard = identityGuard(manifest, plan);
  const guardFinding = guard ? applyIdentityGuard(guard, plan) : null;
  if (guard) console.log('[extract] IDENTITY GUARD: ' + guard.message);
  fs.writeFileSync(path.join(OUT, 'plan.json'), JSON.stringify(plan, null, 2));

  const rulebook = JSON.parse(fs.readFileSync(path.join(ROOT, 'rulebook.json'), 'utf8'));
  const codeFindings = validate(plan, manifest, rulebook);
  if (guardFinding) codeFindings.unshift(guardFinding);
  const modelFindings = parseFindings(result.judgement_findings).map((f) => ({ ...f, origin: 'model' }));
  const order = { blocker: 0, missing: 1, gap: 2, inconsistent: 3, watch: 4, housekeeping: 5 };
  const findings = [...codeFindings, ...modelFindings]
    .sort((a, b) => (order[a.severity] ?? 9) - (order[b.severity] ?? 9));
  fs.writeFileSync(path.join(OUT, 'findings.json'), JSON.stringify({
    generated_at: new Date().toISOString(),
    origins: { code: codeFindings.length, model: modelFindings.length },
    findings,
  }, null, 2));

  const messages = sanitize(result.chase_messages || []);
  fs.writeFileSync(path.join(OUT, 'messages.json'), JSON.stringify(messages, null, 2));
  fs.writeFileSync(path.join(OUT, 'chase_messages.md'), renderChaseMd(messages));
  console.log(`[stage] validate-done code=${codeFindings.length} model=${modelFindings.length}`);
  console.log('[extract] wrote plan.json, findings.json, messages.json, chase_messages.md, manifest.json');
}

main().catch((e) => {
  const status = e && e.status ? ` (HTTP ${e.status})` : '';
  const hint = e && e.status === 429
    ? ' - rate limited even after retries; the key\'s per-minute token window is exhausted. Wait a minute and run again.'
    : (e && e.status >= 500 ? ' - Anthropic service issue; run again shortly.' : '');
  console.error(`[extract] FAILED${status}:`, (e && e.message || e) + hint);
  process.exit(1);
});
