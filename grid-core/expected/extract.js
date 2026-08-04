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
// Env: ANTHROPIC_API_KEY (or grid-core/.env), EXPECTED_MODEL (default claude-opus-5)
'use strict';

const fs = require('fs');
const path = require('path');
const { preprocess } = require('./preprocess');
const { validate } = require('./validate');

const ROOT = __dirname;
const OUT = path.join(ROOT, 'out');
const MODEL = process.env.EXPECTED_MODEL || 'claude-opus-5';

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

// ---- schema helpers (structured outputs require additionalProperties:false
// and a full required list on every object; nullability via type unions)
const obj = (props) => ({ type: 'object', properties: props, required: Object.keys(props), additionalProperties: false });
const arr = (items) => ({ type: 'array', items });
const str = { type: 'string' };
const nstr = { type: ['string', 'null'] };
const nnum = { type: ['number', 'null'] };

const CITATION = obj({ file: str, location: nstr });
const NCITATION = { ...CITATION, type: ['object', 'null'] };
const CITED_NUM = obj({ value: nnum, citation: NCITATION });
const CITED_STR = obj({ value: nstr, citation: NCITATION });
const DATE_FIELD = obj({
  value: nstr,
  candidates: arr(obj({ value: str, file: str, location: nstr, note: nstr })),
  resolution_rationale: nstr,
});

const SCHEMA = obj({
  plan: obj({
    client: CITED_STR,
    job_number: CITED_STR,
    campaign_name: CITED_STR,
    identification_confidence: { type: 'string', enum: ['high', 'medium', 'low'] },
    currency: CITED_STR,
    total_budget: CITED_NUM,
    fee_treatment: CITED_STR,
    flight_start: DATE_FIELD,
    flight_end: DATE_FIELD,
    stated_duration_days: CITED_NUM,
    campaigns: arr(obj({
      campaign_name: str,
      platform: str,
      budget: CITED_NUM,
      rate_type: nstr,
      rate_value: CITED_NUM,
      goal_impressions: CITED_NUM,
      goal_clicks: CITED_NUM,
      goal_ctr: nnum,
      start: nstr,
      end: nstr,
    })),
    platform_campaigns: obj({
      rows: arr(obj({ name: str, group: nstr, platform: str, budget: nnum, start: nstr, end: nstr, geo: nstr })),
      claimed_total: CITED_NUM,
      source: NCITATION,
    }),
    urls: arr(obj({ url: str, platform: nstr, geo: nstr, context: str })),
    approval_records: arr(obj({ scope: str, status: nstr, source: nstr })),
    referenced_files: arr(str),
    notes: arr(str),
  }),
  judgement_findings: arr(obj({
    severity: { type: 'string', enum: ['blocker', 'missing', 'gap', 'inconsistent', 'watch', 'housekeeping'] },
    chip: str,
    stage: { type: 'string', enum: ['Request Received', 'Media Plan Approved', 'Raw Materials Complete', 'Campaign Built', 'Live', 'Pacing'] },
    title: str,
    detail: str,
    source: str,
  })),
  chase_messages: arr(obj({ recipient: str, title: str, body: str })),
});

const SYSTEM = `You are the extraction engine for the Expected side of The Grid, a media agency's campaign pacing system. You receive a converted dump of a media buyer's campaign files (media plans, briefs/activation forms, platform setup sheets, creative sheets, trackers, bulk uploads) plus a file inventory with media metadata measured in code. You output one structured record.

HARD RULES
- Every extracted value cites its source: file, then sheet and row (the sheets are row-numbered R1, R2, ...). No citation, no value.
- Missing stays missing: a field with no source is null. NEVER invent, infer, or default a value. A confidently wrong number is worse than a gap.
- Conflicting values: list every candidate with its source. Set the resolved value ONLY when the documents themselves resolve it (later documents are unanimous, or the earlier document carries its own revision annotation); explain in resolution_rationale. If no documented resolution exists, value stays null.
- Do no arithmetic. Code reconciles sums, dates, and rates after you. Your job is faithful extraction plus judgement.
- If the dump might contain two different clients or campaigns conflated, set identification_confidence to low and emit a blocker finding: merging two clients' data is the worst failure this system can produce.
- Dates are ISO YYYY-MM-DD. Currency amounts are plain numbers (no symbols). Use "-" only, never em or en dashes, anywhere in any text you produce.

FIELD GUIDANCE
- campaigns: the media plan's budget lines, the pacing grain - one entry per plan line that carries its own budget, cost rate, and volume goals (impressions/clicks). Do NOT put platform build rows here.
- platform_campaigns.rows: the platform-level build rows (e.g. each LinkedIn campaign in a setup grid) with their individual budgets and dates. claimed_total: if the sheet carrying those rows has a TOTAL row or label claiming a total for them, extract that claimed number with its citation - even if you suspect it is wrong. Code checks whether it sums.
- urls: every distinct destination, clickthrough, and confirmation URL in the dump, with the platform it serves on, the market geo as a 2-letter code where determinable, and a short context label.
- approval_records: every approval, sign-off, go-live status, or install-confirmation field you find - one entry per scope (e.g. "media plan sign-off", "doc ads creative", "statics and video creative", "tracking tag install test"). status is the recorded value, or null when the field exists but nothing is recorded. Missing sign-off for the plan itself belongs here too (status null, source "absent from all supplied files").
- referenced_files: every asset file NAME any document references (creative file names, PDFs in bulk uploads or trackers), so code can flag files present in the dump that nothing references.

JUDGEMENT FINDINGS (yours; code handles all arithmetic)
Flag what a careful media operations lead would flag but arithmetic cannot catch: expectation gaps between what a brief states and what the plan contracts (budget figures, KPI framing such as leads-vs-impressions); scope that changed between document versions with no recorded decision; documents whose printed values were superseded but never re-issued; sheets in a workbook that belong to a different campaign; installs or tests that were instructed but never confirmed. Severity: blocker = a stage's defining artifact is missing or the campaign cannot be trusted to launch/reconcile; gap = stated expectation contradicts an agreed one; missing/inconsistent/watch/housekeeping as they read. Assign each to the stage where it bites.

CHASE MESSAGES
Draft one message per recipient, consolidating everything that recipient owes (typically: one to the client contact, one internal to the media team). Tone rules: warm opener naming the campaign; acknowledge what has already been received; the specific list of what is needed with exact specifications; why it matters framed as impact on their campaign; a clear date derived from real arithmetic (flight end, wash-up), never an invented deadline; an offer of help. Never assign blame - no "as previously requested", no "still waiting". Short paragraphs a person can act on from a phone. Plain text, no markdown headers inside the body.`;

function sanitize(x) {
  if (typeof x === 'string') return x.replace(/[–—]/g, '-');
  if (Array.isArray(x)) return x.map(sanitize);
  if (x && typeof x === 'object') {
    const o = {};
    for (const k of Object.keys(x)) o[k] = sanitize(x[k]);
    return o;
  }
  return x;
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
  if (!process.env.ANTHROPIC_API_KEY) {
    console.error('[extract] BLOCKED: no ANTHROPIC_API_KEY in the environment or grid-core/.env');
    process.exit(2);
  }

  fs.mkdirSync(OUT, { recursive: true });
  console.log(`[extract] preprocessing ${filesDir}`);
  const { manifest, bundleText } = preprocess(filesDir);
  fs.writeFileSync(path.join(OUT, 'manifest.json'), JSON.stringify(manifest, null, 2));
  console.log(`[stage] preprocess-done files=${manifest.files.length} bundle_chars=${bundleText.length}`);

  const Anthropic = require('@anthropic-ai/sdk');
  const client = new Anthropic();
  console.log(`[stage] model-start model=${MODEL}`);
  const raw = await callClaude(client, bundleText);
  const result = sanitize(raw);
  console.log('[stage] model-done');

  const plan = result.plan;
  plan.extractor = { model: MODEL, generated_at: new Date().toISOString(), dump_dir: filesDir, one_call: true };
  fs.writeFileSync(path.join(OUT, 'plan.json'), JSON.stringify(plan, null, 2));

  const rulebook = JSON.parse(fs.readFileSync(path.join(ROOT, 'rulebook.json'), 'utf8'));
  const codeFindings = validate(plan, manifest, rulebook);
  const modelFindings = (result.judgement_findings || []).map((f) => ({ ...f, origin: 'model' }));
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
  console.error('[extract] FAILED:', e && e.message || e);
  process.exit(1);
});
