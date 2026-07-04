// Minimal ANSI colour + fixed-width table rendering. No dependencies.

const useColor = process.stdout.isTTY && !process.env.NO_COLOR;

const CODES = {
  reset: 0, bold: 1, dim: 2,
  red: 31, green: 32, yellow: 33, blue: 34, gray: 90,
};

export function c(name, s) {
  if (!useColor || !CODES[name]) return s;
  return `\x1b[${CODES[name]}m${s}\x1b[0m`;
}

/** Visible length ignoring ANSI escape codes (for column alignment). */
function visLen(s) {
  return String(s).replace(/\x1b\[[0-9;]*m/g, '').length;
}

function pad(s, width) {
  const gap = width - visLen(s);
  return gap > 0 ? s + ' '.repeat(gap) : s;
}

/**
 * Render an aligned table.
 * @param {string[]} headers
 * @param {string[][]} rows  cells may already contain ANSI colour codes
 */
export function renderTable(headers, rows) {
  const widths = headers.map((h, i) =>
    Math.max(visLen(h), ...rows.map((r) => visLen(r[i] ?? '')))
  );
  const sep = '  ';
  const line = (cells) => cells.map((cell, i) => pad(cell ?? '', widths[i])).join(sep);
  const rule = widths.map((w) => '─'.repeat(w)).join(sep);

  const out = [];
  out.push(c('bold', line(headers)));
  out.push(c('gray', rule));
  for (const r of rows) out.push(line(r));
  return out.join('\n');
}
