// Generic deterministic checks over an extracted plan.json + the preprocess
// manifest, driven by rulebook.json so they run identically for every client.
// The model never does arithmetic; these findings carry origin "code".
// Judgement findings come from the extractor tagged origin "model".
'use strict';

const DAY_MS = 86400000;

function parseDate(s) {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(s || '');
  return m ? Date.UTC(+m[1], +m[2] - 1, +m[3]) : null;
}

function val(node) {
  return node && node.value != null ? node.value : null;
}

function cite(node) {
  if (!node || !node.citation) return 'extracted plan.json';
  return `${node.citation.file}${node.citation.location ? ', ' + node.citation.location : ''}`;
}

function finding(id, severity, stage, chip, title, detail, source) {
  return { id, severity, stage, chip, title, detail, source, origin: 'code' };
}

function inclusiveDays(startMs, endMs) {
  return Math.round((endMs - startMs) / DAY_MS) + 1;
}

function validate(plan, manifest, rulebook) {
  const out = [];
  const rb = rulebook;
  const money = rb.money;

  const campaigns = plan.campaigns || [];
  const total = val(plan.total_budget);
  const flightStart = parseDate(val(plan.flight_start));
  const flightEnd = parseDate(val(plan.flight_end));
  const flightDays = flightStart != null && flightEnd != null ? inclusiveDays(flightStart, flightEnd) : null;

  // -------- money: campaign budgets sum to the stated total
  if (total != null && campaigns.length) {
    const sum = campaigns.reduce((a, c) => a + (val(c.budget) || 0), 0);
    if (Math.abs(sum - total) > money.budget_sum_tolerance) {
      out.push(finding('m_sum', 'inconsistent', 'Media Plan Approved', 'INCONSISTENT',
        `Campaign budgets sum to ${sum.toLocaleString()} against a stated total of ${total.toLocaleString()}`,
        'Line budgets and the plan total disagree.', cite(plan.total_budget)));
    }
  }

  // -------- money: a claimed total that does not sum (cross-document label check)
  const pc = plan.platform_campaigns;
  if (pc && pc.rows && pc.rows.length && pc.claimed_total && val(pc.claimed_total) != null) {
    const rowSum = pc.rows.reduce((a, r) => a + (r.budget || 0), 0);
    const claimed = val(pc.claimed_total);
    if (Math.abs(rowSum - claimed) > money.budget_sum_tolerance) {
      out.push(finding('m_label', 'inconsistent', 'Campaign Built', 'INCONSISTENT',
        `A total row claims ${claimed.toLocaleString()} over ${pc.rows.length} platform campaigns that sum to ${rowSum.toLocaleString()}`,
        'The label on the build sheet contradicts its own rows.', cite(pc.claimed_total)));
    }
  }

  // -------- money: impressions/clicks reconcile with budget and rate
  for (const c of campaigns) {
    const budget = val(c.budget);
    const rate = val(c.rate_value);
    const imps = val(c.goal_impressions);
    const clicks = val(c.goal_clicks);
    const ctr = c.goal_ctr != null && typeof c.goal_ctr === 'number' ? c.goal_ctr : null;
    if (budget != null && rate != null && (c.rate_type || '').toUpperCase() === 'CPM' && imps != null) {
      const derived = (budget / rate) * 1000;
      const tol = Math.max(money.rate_reconcile_abs_tolerance, money.rate_reconcile_rel_tolerance * Math.max(derived, imps));
      if (Math.abs(derived - imps) > tol) {
        out.push(finding(`m_rate_${c.campaign_name}`, 'inconsistent', 'Media Plan Approved', 'INCONSISTENT',
          `${c.campaign_name}: budget ${budget} at ${rate} CPM implies ${Math.round(derived).toLocaleString()} impressions, plan states ${imps.toLocaleString()}`,
          'Impressions do not reconcile with budget and cost rate.', cite(c.budget)));
      }
      if (ctr != null && clicks != null) {
        const dClicks = imps * ctr;
        if (Math.abs(dClicks - clicks) > Math.max(money.rate_reconcile_abs_tolerance, money.rate_reconcile_rel_tolerance * Math.max(dClicks, clicks))) {
          out.push(finding(`m_ctr_${c.campaign_name}`, 'inconsistent', 'Media Plan Approved', 'INCONSISTENT',
            `${c.campaign_name}: ${imps.toLocaleString()} impressions at ${(ctr * 100).toFixed(2)}% CTR implies ${Math.round(dClicks)} clicks, plan states ${clicks}`,
            'Clicks do not reconcile with impressions and CTR.', cite(c.budget)));
        }
      }
    }
  }

  // -------- dates: stated duration vs computed inclusive days
  if (rb.dates.check_stated_duration && flightDays != null && val(plan.stated_duration_days) != null) {
    const stated = val(plan.stated_duration_days);
    if (stated !== flightDays) {
      out.push(finding('d_dur', 'inconsistent', 'Media Plan Approved', 'INCONSISTENT',
        `Stated duration ${stated} days; the resolved flight ${val(plan.flight_start)} to ${val(plan.flight_end)} inclusive is ${flightDays} days`,
        'Harmless until someone divides a budget by the wrong number. The baseline uses the computed day count.', cite(plan.stated_duration_days)));
    }
  }

  // -------- dates: conflicting flight windows surfaced by the extractor
  for (const key of ['flight_start', 'flight_end']) {
    const f = plan[key];
    if (f && Array.isArray(f.candidates) && f.candidates.length > 1) {
      const cands = f.candidates.map((c) => `${c.value} (${c.file || 'unknown source'})`).join(' vs ');
      out.push(finding(`d_conflict_${key}`, 'inconsistent', 'Media Plan Approved', 'INCONSISTENT',
        `Conflicting ${key.replace('_', ' ')} across documents: ${cands}`,
        f.resolution_rationale ? `Resolved for the baseline: ${f.value}. ${f.resolution_rationale}` : 'No documented resolution; the field is null and the baseline cannot be generated.',
        f.candidates.map((c) => c.file).filter(Boolean).join('; ')));
    }
  }

  // -------- dates: items within flight
  if (rb.dates.check_items_within_flight && flightStart != null && flightEnd != null && pc && pc.rows) {
    for (const r of pc.rows) {
      const s = parseDate(r.start);
      const e = parseDate(r.end);
      if ((s != null && s < flightStart) || (e != null && e > flightEnd)) {
        out.push(finding(`d_out_${r.name}`, 'inconsistent', 'Campaign Built', 'INCONSISTENT',
          `${r.name}: dates ${r.start} to ${r.end} fall outside the campaign flight`, '', cite(pc.claimed_total) || 'platform campaign rows'));
      }
    }
  }

  // -------- platform minimums: sub-minimum daily budgets
  if (pc && pc.rows) {
    const min = rb.platform_minimums.linkedin_min_daily_budget;
    for (const r of pc.rows) {
      const s = parseDate(r.start) ?? flightStart;
      const e = parseDate(r.end) ?? flightEnd;
      if (s == null || e == null || !(r.budget > 0)) continue;
      if (!/linkedin/i.test(r.platform || '')) continue;
      const daily = r.budget / inclusiveDays(s, e);
      if (daily < min) {
        out.push(finding(`p_min_${r.name}`, 'watch', 'Campaign Built', 'WATCH',
          `${r.name}: ${daily.toFixed(2)}/day is under LinkedIn's ${min}/day minimum`,
          `Lifetime ${r.budget} over ${inclusiveDays(s, e)} days. It will pace at the floor or be capped; check at the first pacing review.`,
          'computed from platform campaign rows'));
      }
    }
  }

  // -------- utm checks over every extracted URL
  const urls = plan.urls || [];
  const monthTokens = new Map();
  const monthRe = new RegExp(rb.utm.month_token_pattern);
  for (const u of urls) {
    let parsed;
    try { parsed = new URL(u.url); } catch {
      out.push(finding(`u_bad_${u.context}`, 'inconsistent', 'Campaign Built', 'INCONSISTENT', `Malformed URL (${u.context})`, u.url, u.context));
      continue;
    }
    const q = parsed.searchParams;
    for (const p of rb.utm.required_params) {
      if (!q.get(p)) out.push(finding(`u_p_${u.context}_${p}`, 'inconsistent', 'Campaign Built', 'INCONSISTENT', `URL missing ${p} (${u.context})`, u.url.slice(0, 120), u.context));
    }
    const src = (q.get('utm_source') || '').toLowerCase();
    const expected = rb.utm.platform_source_map[(u.platform || '').toLowerCase()];
    if (src && expected && src !== expected) {
      out.push(finding(`u_src_${u.context}`, 'watch', 'Campaign Built', 'WATCH', `utm_source=${src} on a ${u.platform} placement (${u.context})`, '', u.context));
    }
    if (rb.utm.check_month_token_consistency) {
      const m = monthRe.exec(q.get('utm_campaign') || '');
      if (m) {
        if (!monthTokens.has(m[2])) monthTokens.set(m[2], 0);
        monthTokens.set(m[2], monthTokens.get(m[2]) + 1);
      }
    }
    if (rb.utm.check_geo_id_prefix && (u.geo || '').toUpperCase() !== 'AU') {
      const id = q.get('utm_id') || '';
      const geoPrefix = /^([a-z]{2})_/.exec(id);
      if (geoPrefix && u.geo && geoPrefix[1].toUpperCase() !== u.geo.toUpperCase() && u.geo.length === 2) {
        out.push(finding(`u_geo_${u.context}`, 'watch', 'Campaign Built', 'WATCH',
          `${u.geo} destination carries a ${geoPrefix[1]}_ utm_id (${u.context})`,
          'Traffic will be tagged with another market\'s campaign id in analytics.', u.context));
      }
    }
  }
  if (monthTokens.size > 1) {
    const desc = [...monthTokens.entries()].map(([mo, n]) => `${mo} (${n} urls)`).join(' vs ');
    out.push(finding('u_scheme', 'inconsistent', 'Campaign Built', 'INCONSISTENT',
      `Inconsistent utm_campaign month tokens across the campaign: ${desc}`,
      'Analytics will split one campaign across multiple utm_campaign vintages.', 'all extracted URLs'));
  }

  // -------- approvals: recorded columns/fields with empty status
  if (rb.approvals.flag_null_status) {
    for (const a of plan.approval_records || []) {
      if (a.status == null || a.status === '') {
        out.push(finding(`a_${a.scope}`, 'missing', 'Raw Materials Complete', 'MISSING',
          `No recorded approval: ${a.scope}`, 'An approval field exists but nothing is recorded in it.', a.source || 'extracted approval records'));
      }
    }
  }

  // -------- files: unreferenced media + duplicates
  const referenced = new Set((plan.referenced_files || []).map((f) => f.toLowerCase()));
  const refHashes = new Set();
  const manFiles = (manifest && manifest.files) || [];
  for (const f of manFiles) {
    const base = f.file.split('/').pop().toLowerCase();
    if (referenced.has(base) || [...referenced].some((r) => f.file.toLowerCase().endsWith(r))) refHashes.add(f.sha256);
  }
  for (const f of manFiles) {
    if (!rb.files.flag_unreferenced_media_types.includes(f.type)) continue;
    const base = f.file.split('/').pop().toLowerCase();
    const isRef = referenced.has(base) || [...referenced].some((r) => f.file.toLowerCase().endsWith(r));
    if (isRef || refHashes.has(f.sha256)) continue; // referenced, or a byte-copy of something referenced
    out.push(finding(`f_orphan_${f.file}`, 'watch', 'Raw Materials Complete', 'UNREFERENCED',
      `Media file referenced by nothing: ${f.file}`, 'Present in the dump but cited by no plan document. Purpose unknown.', 'file inventory (hashes computed in code)'));
  }
  // -------- files: referenced by a document but ABSENT from the dump.
  // The mirror image of the orphan check above: that one asks "what is here that
  // nothing cites", this asks "what do the documents cite that nobody sent".
  // These are the files a buyer still owes, so each one names itself - the run
  // continues on what did arrive and the gap is explicit rather than silent.
  const present = manFiles.map((f) => f.file.toLowerCase());
  const missingRefs = [];
  for (const ref of plan.referenced_files || []) {
    const name = String(ref).trim();
    if (!name) continue;
    const lower = name.toLowerCase();
    const found = present.some((p) => p === lower || p.endsWith('/' + lower) || p.split('/').pop() === lower);
    if (!found) missingRefs.push(name);
  }
  if (missingRefs.length) {
    out.push(finding('f_missing', 'missing', 'Raw Materials Complete', 'NOT SUPPLIED',
      `${missingRefs.length} file(s) referenced by the campaign documents were not supplied`,
      `Upload these to complete the audit: ${missingRefs.join('; ')}. Everything else was analysed; only checks that need these files are outstanding.`,
      'referenced file names vs the file inventory'));
  }

  // -------- files: present in the dump but never READ (no converter here).
  // Their content never reached the model, so any figure or approval inside
  // them is invisible to this run - say so rather than letting the audit imply
  // the file was considered.
  const unread = manFiles.filter((f) => f.converted === false || f.parse_error);
  if (unread.length) {
    out.push(finding('f_unread', 'missing', 'Raw Materials Complete', 'NOT READ',
      `${unread.length} supplied file(s) could not be read, so their contents were not audited`,
      unread.map((f) => `${f.file}${f.parse_error ? ` (parse error: ${f.parse_error})` : ' (no converter for this format)'}`).join('; ')
        + '. Re-supply these as .xlsx/.csv/.pdf if they carry plan figures, approvals or asset lists.',
      'file inventory (conversion results computed in code)'));
  }

  if (rb.files.flag_duplicates) {
    const dups = manFiles.filter((f) => f.duplicate_of);
    if (dups.length) {
      out.push(finding('f_dups', 'housekeeping', 'Raw Materials Complete', 'HOUSEKEEPING',
        `${dups.length} byte-identical duplicate file(s) in the dump`,
        dups.map((d) => `${d.file} = ${d.duplicate_of}`).join('; '), 'file hashes computed in code'));
    }
  }

  return out;
}

module.exports = { validate, parseDate, inclusiveDays };
