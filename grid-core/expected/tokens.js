// Token estimation for a Greenlight run, so a buyer can see what a run will
// cost BEFORE paying for it (preprocess is free and deterministic, so the
// bundle size is knowable in advance - only the model call costs anything).
//
// The estimate SELF-CALIBRATES: every successful run records its real
// chars-per-token, and the next estimate uses the observed average. The seed
// value only matters until the first run lands.
//
// No dollar figures anywhere. Greenlight bills a Kimi subscription with no
// per-call price this code can read, and an invented number is worse than
// none - same rule the extractor follows for plan values.
'use strict';

const fs = require('fs');
const path = require('path');

// Row-numbered CSV tokenizes far denser than prose: digits, commas and the
// "R12: " prefixes each cost a token, so ~2.5 chars/token rather than the ~4
// typical of English. A rough prior, replaced by measurement after run one.
const SEED_CHARS_PER_TOKEN = 2.5;
const MIN_RATIO = 1.2;   // guard against a bogus observation poisoning the estimate
const MAX_RATIO = 8;
const MAX_SAMPLES = 20;

function calFile(dumpsDir) {
  return path.join(dumpsDir, '_token_calibration.json');
}

function readCal(dumpsDir) {
  try {
    const c = JSON.parse(fs.readFileSync(calFile(dumpsDir), 'utf8'));
    if (Array.isArray(c.samples) && c.samples.length) return c;
  } catch { /* first run, or unreadable - fall through to the seed */ }
  return { samples: [] };
}

/** Mean observed chars-per-token, or the seed when nothing has been measured. */
function ratio(dumpsDir) {
  const { samples } = readCal(dumpsDir);
  if (!samples.length) return { value: SEED_CHARS_PER_TOKEN, calibrated: false, samples: 0 };
  const mean = samples.reduce((a, s) => a + s, 0) / samples.length;
  return { value: mean, calibrated: true, samples: samples.length };
}

/** Record one real observation (bundle chars -> reported input tokens). */
function observe(dumpsDir, chars, inputTokens) {
  if (!(chars > 0) || !(inputTokens > 0)) return null;
  const r = chars / inputTokens;
  if (r < MIN_RATIO || r > MAX_RATIO) return null;   // implausible, ignore
  const cal = readCal(dumpsDir);
  cal.samples = cal.samples.concat(r).slice(-MAX_SAMPLES);
  cal.updated_at = new Date().toISOString();
  try {
    fs.mkdirSync(dumpsDir, { recursive: true });
    fs.writeFileSync(calFile(dumpsDir), JSON.stringify(cal, null, 2));
  } catch (e) {
    console.error('[greenlight][tokens] could not persist calibration:', e.message);
  }
  return r;
}

/**
 * estimate(dumpsDir, bundleChars, systemChars) -> what the model call will cost
 * in tokens. Output is bounded by the schema rather than by the input, so it is
 * reported as the configured ceiling, not as a guess.
 */
function estimate(dumpsDir, bundleChars, systemChars, maxOutputTokens) {
  const r = ratio(dumpsDir);
  const input = Math.round((bundleChars + (systemChars || 0)) / r.value);
  return {
    input_tokens: input,
    output_tokens_max: maxOutputTokens || null,
    chars: bundleChars,
    chars_per_token: Math.round(r.value * 100) / 100,
    calibrated: r.calibrated,
    samples: r.samples,
    // +/- 25% until a few real runs have been measured, +/- 10% after
    accuracy: r.calibrated ? 0.10 : 0.25,
  };
}

module.exports = { estimate, observe, ratio, SEED_CHARS_PER_TOKEN };
