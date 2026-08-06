/*
 * expected/validate.test.js - locks the deterministic rulebook checks.
 *
 * Two things matter equally: a check must FIRE on a real discrepancy, and it
 * must NOT fire on figures that reconcile. A validator that flags everything
 * trains people to skim the findings list, which defeats the flowchart above it.
 *
 * Free, deterministic, no key, no server, no network.
 */
'use strict';
const { validate } = require('./validate');
const rulebook = require('./rulebook.json');

let pass = 0, fail = 0;
const check = (n, c, x) => { if (c) { pass++; console.log('  ✓', n); } else { fail++; console.log('  ✗', n, x !== undefined ? JSON.stringify(x) : ''); } };

const cited = (value) => ({ value, citation: { file: 'media_plan.xlsx', location: "sheet 'Plan', row 8" } });
const line = (name, budget, extra) => Object.assign({
  campaign_name: name, platform: 'LinkedIn',
  budget: cited(budget), rate_type: 'CPM', rate_value: cited(null),
  goal_impressions: cited(null), goal_clicks: cited(null), goal_ctr: null,
  start: '2026-06-01', end: '2026-08-22',
}, extra || {});

// A plan where everything reconciles. Every "does not fire" case starts here.
const clean = () => ({
  client: cited('Acme'), job_number: cited('2053'), campaign_name: cited('Launch'),
  currency: cited('AUD'), total_budget: cited(20000),
  flight_start: { value: '2026-06-01', candidates: [], resolution_rationale: null },
  flight_end: { value: '2026-08-22', candidates: [], resolution_rationale: null },
  stated_duration_days: cited(83),      // 2026-06-01..08-22 inclusive IS 83
  campaigns: [line('LinkedIn A', 6000), line('Programmatic', 14000)],
  platform_campaigns: { rows: [], claimed_total: { value: null, citation: null } },
  urls: [], approval_records: [], referenced_files: [], name_collisions: [],
});
const manifest = (files, intake) => ({ files: files || [], intake: intake || undefined });
const run = (plan, man) => validate(plan, man || manifest(), rulebook);
const ids = (out) => out.map((f) => f.id);
const has = (out, id) => ids(out).includes(id);

// ---- the baseline: a clean plan raises nothing ----
check('clean plan raises no findings', run(clean()).length === 0, ids(run(clean())));

// ---- money ----
const badSum = clean(); badSum.total_budget = cited(35000);
check('budget mismatch fires', has(run(badSum), 'm_sum'));
check('budget mismatch names both figures', /35,000/.test(run(badSum)[0].title) && /20,000/.test(run(badSum)[0].title), run(badSum)[0].title);

const claimed = clean();
claimed.platform_campaigns = {
  rows: [{ name: 'a', platform: 'LinkedIn', budget: 9000, start: null, end: null },
    { name: 'b', platform: 'LinkedIn', budget: 9000, start: null, end: null },
    { name: 'c', platform: 'LinkedIn', budget: 9000, start: null, end: null }],
  claimed_total: cited(35000),
};
check('claimed total that does not sum fires', has(run(claimed), 'm_label'));

const cpmOk = clean();
cpmOk.campaigns = [line('X', 6000, { rate_value: cited(20), goal_impressions: cited(300000) })];
cpmOk.total_budget = cited(6000);
check('CPM that reconciles does NOT fire', !has(run(cpmOk), 'm_rate_X'), ids(run(cpmOk)));

const cpmBad = clean();
cpmBad.campaigns = [line('X', 6000, { rate_value: cited(20), goal_impressions: cited(500000) })];
cpmBad.total_budget = cited(6000);
check('CPM that does not reconcile fires', has(run(cpmBad), 'm_rate_X'));

// ---- dates ----
const dur = clean(); dur.stated_duration_days = cited(82);
check('stated 82 vs computed 83 days fires', has(run(dur), 'd_dur'));
check('inclusive day count is 83, not 82', /83 days/.test(run(dur)[0].title), run(dur)[0].title);

const conflict = clean();
conflict.flight_start = { value: '2026-06-01', resolution_rationale: 'later docs agree',
  candidates: [{ value: '2026-06-01', file: 'a.xlsx' }, { value: '2026-05-01', file: 'b.xlsx' }] };
check('conflicting flight starts fire', has(run(conflict), 'd_conflict_flight_start'));

const outside = clean();
outside.platform_campaigns = { rows: [{ name: 'late', platform: 'LinkedIn', budget: 100, start: '2026-06-01', end: '2026-12-01' }], claimed_total: { value: null, citation: null } };
check('build row outside the flight fires', has(run(outside), 'd_out_late'));

// ---- platform minimums ----
const min = clean();
min.platform_campaigns = { rows: [{ name: 'tiny', platform: 'LinkedIn', budget: 100, start: '2026-06-01', end: '2026-08-22' }], claimed_total: { value: null, citation: null } };
check('sub-minimum LinkedIn daily budget fires', has(run(min), 'p_min_tiny'));
const minOk = clean();
minOk.platform_campaigns = { rows: [{ name: 'fine', platform: 'LinkedIn', budget: 5000, start: '2026-06-01', end: '2026-08-22' }], claimed_total: { value: null, citation: null } };
check('healthy LinkedIn daily budget does NOT fire', !has(run(minOk), 'p_min_fine'));

// ---- utm ----
const utm = clean();
utm.urls = [{ url: 'https://x.com/p?utm_source=linkedin&utm_medium=paid&utm_campaign=2026_jun_anz', platform: 'LinkedIn', geo: 'AU', context: 'lp' }];
check('a well-formed tagged URL raises nothing', run(utm).length === 0, ids(run(utm)));
const utmBad = clean();
utmBad.urls = [{ url: 'not a url', platform: 'LinkedIn', geo: 'AU', context: 'lp' }];
check('malformed URL fires', has(run(utmBad), 'u_bad_lp'));

// ---- approvals ----
const appr = clean();
appr.approval_records = [{ scope: 'media plan sign-off', status: null, source: 'absent' }];
check('blank approval fires', has(run(appr), 'a_media plan sign-off'));
const apprOk = clean();
apprOk.approval_records = [{ scope: 'media plan sign-off', status: 'Approved 2026-05-20', source: 'brief.xlsx' }];
check('recorded approval does NOT fire', run(apprOk).length === 0, ids(run(apprOk)));

// ---- INTAKE: the new checks. Anything the pipeline could not read is visible.
const unread = run(clean(), manifest([], {
  unread: ['brief.pdf', 'deck.pptx'], parse_errors: [], truncated_sheets: [], sampled_csvs: [],
}));
check('unread files fire a finding', has(unread, 'i_unread'));
check('unread finding is severity missing', unread[0].severity === 'missing', unread[0].severity);
check('unread finding names the files', /brief\.pdf/.test(unread[0].detail));

const parseErr = run(clean(), manifest([], {
  unread: [], parse_errors: [{ file: 'locked.xlsx', error: 'Unsupported ZIP encryption' }], truncated_sheets: [], sampled_csvs: [],
}));
check('parse error fires a finding', has(parseErr, 'i_parse_locked.xlsx'));
check('parse-error finding carries the reason', /ZIP encryption/.test(parseErr[0].detail));

const trunc = run(clean(), manifest([], {
  unread: [], parse_errors: [], truncated_sheets: ["plan.xlsx | sheet 'Big'"], sampled_csvs: [],
}));
check('truncated sheet fires a finding', has(trunc, 'i_trunc'));

const sampled = run(clean(), manifest([], {
  unread: [], parse_errors: [], truncated_sheets: [], sampled_csvs: ['audience.csv (5000 rows)'],
}));
check('head-sampled CSV fires a finding', has(sampled, 'i_sampled'));

const cleanIntake = run(clean(), manifest([], { unread: [], parse_errors: [], truncated_sheets: [], sampled_csvs: [] }));
check('a fully-read dump raises no intake findings', cleanIntake.length === 0, ids(cleanIntake));

// an OLD manifest (restored from the extract slot) has no intake block at all
const oldManifest = run(clean(), { files: [] });
check('a pre-intake manifest does not throw', Array.isArray(oldManifest) && oldManifest.length === 0);

// ---- duplicate campaign names surfaced by normalizePlan ----
const dupName = clean();
dupName.name_collisions = [{ name: 'Awareness', renamed_to: 'Awareness (2)' }];
check('duplicate campaign name fires', has(dupName ? run(dupName) : [], 'x_dupname_Awareness (2)'), ids(run(dupName)));

// ---- files ----
const orphan = run(clean(), manifest([{ file: 'creatives/banner.jpg', type: 'image', sha256: 'aaa' }]));
check('unreferenced media fires', has(orphan, 'f_orphan_creatives/banner.jpg'));
const referenced = clean(); referenced.referenced_files = ['banner.jpg'];
check('referenced media does NOT fire',
  !has(validate(referenced, manifest([{ file: 'creatives/banner.jpg', type: 'image', sha256: 'aaa' }]), rulebook), 'f_orphan_creatives/banner.jpg'));
const dups = run(clean(), manifest([{ file: 'b.jpg', type: 'image', sha256: 'a', duplicate_of: 'a.jpg' }]));
check('byte-identical duplicates fire once', dups.filter((f) => f.id === 'f_dups').length === 1);

// ---- every finding is well-formed (the UI renders these fields directly) ----
const all = run(badSum).concat(unread, parseErr, trunc, sampled);
check('every finding has severity/stage/chip/title/origin',
  all.every((f) => f.severity && f.stage && f.chip && f.title && f.origin === 'code'));
check('every severity is a known one',
  all.every((f) => ['blocker', 'missing', 'gap', 'inconsistent', 'watch', 'housekeeping'].includes(f.severity)));
check('every stage is a known one', all.every((f) => rulebook.stages.includes(f.stage)));
check('no em or en dashes in any finding text', !/[–—]/.test(JSON.stringify(all)));

console.log('\n' + (fail ? '✗' : '✓') + ' validate: ' + pass + ' passed, ' + fail + ' failed');
process.exit(fail ? 1 : 0);
