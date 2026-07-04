/* bb_deck.js — the ONE canonical, theme-driven slide-deck builder for every client's
 * "Download slides" feature. Vendored per dash folder (like freshness.py / platform_sso.py):
 * edit THIS canonical copy, then re-copy it into each clients/client_<c>/dash/ and redeploy.
 *
 * Builds a 4-slide, board-ready .pptx (Cover · What happened · Why · Recommended actions) ENTIRELY
 * in the browser with PptxGenJS; Google Slides opens it natively (drag into Drive → editable Slides).
 * The DESIGN LANGUAGE is MongoDB's brand deck — serif headlines, "ALL CAPS" mono accent pills,
 * organic corner blobs, a logo/leaf top-right, a dark cover + light content slides — and it is
 * RECOLOURED PER CLIENT from the `theme` object the caller passes, so every client's deck shares one
 * layout but wears its own palette + logo.
 *
 * PUBLIC API:  await bbBuildDeck(report, payload, theme, logos, opts)
 *   report  = the /report JSON: {headline, campaign_type?, overall_status, slide1{summary,kpis[]},
 *             slide2{summary,drivers[]}, slide3{summary,actions[]}, confidence_note, sources[],
 *             provider?, model?}.  KPI/driver/action "category" is read tolerantly as
 *             (category || engine || area) so this one builder serves every client's report schema.
 *   payload = what the dashboard POSTed: {context:{campaign, markets, all_markets, window{start,end,days},
 *             data_through, generated_at, ...}}.  Slide-1 KPI numbers come VERBATIM from the model's
 *             copy of these figures (the model writes narrative, never numbers).
 *   theme   = per-client palette + fonts (hex WITHOUT '#'); see BB_THEME in each dashboard.html.
 *   logos   = {white: dataURI|null, dark: dataURI|null} — logo rasterised light (for dark slides) and
 *             native/dark (for light slides). Either may be null → a styled text wordmark falls back.
 *   opts    = {download:true (default) → pres.writeFile; false → returns the Blob}.
 *
 * Verified against the PptxGenJS 4.0.1 API: color = hex WITHOUT '#'; fill = {color[,transparency]};
 * borderless shapes OMIT `line`; addImage data drops the 'data:' prefix; fit:'shrink' is belt-only
 * (the JS length clamps are the real overflow guard); download via writeFile({fileName}). All fonts
 * are Google-Slides-safe (Georgia serif / Arial sans / Courier New mono) — brand fonts don't survive
 * import, so the wordmark rides in as a rasterised PNG instead.
 */
(function (global) {
  'use strict';

  // ── theme defaults (a partial theme still renders) — MongoDB values are the reference ─────────
  const DEF = {
    bg: '001E2B', panel: '023430', accent: '00ED64', accentInk: '001E2B',
    softBg: 'E3FCF7', lightBg: 'FFFFFF', ink: '001E2B', mute: '5A6B78', line: 'E5E9EE',
    onDark: 'FFFFFF', onDarkMute: '9FB4BE', card: 'FFFFFF',
    serif: 'Georgia', sans: 'Arial', mono: 'Courier New',
    agency: 'Transmission', client: '', brand: '', filePrefix: 'Report',
  };
  const hx = c => String(c == null ? '' : c).replace(/^#/, '');

  // semantic (non-brand) status colours — paired ALWAYS with a word so the deck reads in B&W
  const GOOD = '1E8E3E', BAD = 'C8362A', WARN = 'B97400';
  const STATUS = {
    ahead: { label: 'Ahead of plan', hex: GOOD }, on_track: { label: 'On track', hex: GOOD },
    at_risk: { label: 'At risk', hex: WARN }, behind: { label: 'Behind plan', hex: BAD },
    mixed: { label: 'Mixed', hex: WARN }, neutral: { label: 'Monitoring', hex: '6B7785' },
  };
  const DIR = { up: { g: '▲', hex: GOOD }, down: { g: '▼', hex: BAD }, flat: { g: '▬', hex: '6B7785' }, mixed: { g: '◆', hex: WARN } };
  const PRI = { high: { label: 'HIGH PRIORITY', hex: BAD }, medium: { label: 'MED PRIORITY', hex: WARN }, low: { label: 'LOW PRIORITY', hex: '6B7785' } };
  const EFFORT = { low: 'EFFORT · LOW', medium: 'EFFORT · MED', high: 'EFFORT · HIGH' };
  const CONF = { high: 'HIGH CONFIDENCE', medium: 'MEDIUM CONFIDENCE', low: 'LOW CONFIDENCE' };
  // category chip labels — tolerant across every client's report schema (engine|area|category)
  const CAT = {
    content_syndication: 'LEAD ENGINE', paid_display: 'DISPLAY', paid_media: 'PAID MEDIA', budget: 'BUDGET',
    overall: 'OVERALL', both: 'BOTH', external: 'MARKET', measurement: 'MEASUREMENT',
    creative: 'CREATIVE', audience: 'AUDIENCE', budget_pacing: 'PACING', landing_page: 'LANDING',
    funnel: 'FUNNEL', reach: 'REACH', traffic: 'TRAFFIC', leads: 'LEADS', efficiency: 'EFFICIENCY',
    linkedin: 'LINKEDIN', trade_desk: 'TRADE DESK', delivery: 'DELIVERY', abm: 'ABM',
  };
  const catOf = o => (o && (o.category || o.engine || o.area)) || '';
  const catLabel = v => { if (!v) return ''; const k = String(v).toLowerCase(); return CAT[k] || String(v).replace(/_/g, ' ').toUpperCase(); };

  function clamp(s, n) { s = String(s == null ? '' : s); return s.length > n ? s.slice(0, n - 1).replace(/\s+\S*$/, '') + '…' : s; }
  function fmtDate(iso) { const d = iso ? new Date(iso) : null; return d && !isNaN(d) ? d.toLocaleDateString('en-AU', { day: 'numeric', month: 'short', year: 'numeric' }) : '—'; }

  global.bbBuildDeck = async function bbBuildDeck(report, payload, theme, logos, opts) {
    if (typeof PptxGenJS === 'undefined') throw new Error('The slide library (PptxGenJS) failed to load - check your connection and try again.');
    const T = Object.assign({}, DEF, theme || {});
    for (const k of ['bg', 'panel', 'accent', 'accentInk', 'softBg', 'lightBg', 'ink', 'mute', 'line', 'onDark', 'onDarkMute', 'card']) T[k] = hx(T[k]);
    const L = logos || {};
    const ctx = (payload && payload.context) || {};
    const win = ctx.window || {};
    const R = report || {}, S1 = R.slide1 || {}, S2 = R.slide2 || {}, S3 = R.slide3 || {};
    const kpis = (S1.kpis || []).slice(0, 6), drivers = (S2.drivers || []).slice(0, 5), actions = (S3.actions || []).slice(0, 5);
    const sources = R.sources || [];
    const modelLabel = R.provider === 'gemini' ? (R.model || 'Google Gemini') : 'Claude (Opus 4.8)';
    const clientName = T.client || ctx.generated_for || ctx.client || 'Client';
    const brandLine = T.brand || `${T.agency} × ${clientName}`;
    const regions = (ctx.markets || []).length && (ctx.markets || []).length === (ctx.all_markets || []).length
      ? 'All regions' : ((ctx.markets || []).join(', ') || 'All regions');
    const dataThrough = String(ctx.data_through || '').slice(0, 10) || '—';

    const pres = new PptxGenJS();
    pres.defineLayout({ name: 'BB_WIDE', width: 13.33, height: 7.5 });
    pres.layout = 'BB_WIDE';
    pres.author = T.agency; pres.company = T.agency;
    pres.title = `${clientName} - ${ctx.campaign || 'Campaign'}`;
    const ST = pres.ShapeType;

    // ── shared brand furniture ───────────────────────────────────────────────────────────────
    // The signature "ALL CAPS" pill: a filled accent roundRect + mono caps text. Two stacked
    // objects (text-in-autoshape radius imports inconsistently). Returns its width.
    const pill = (sl, x, y, text) => {
      const t = String(text || '').toUpperCase(), w = 0.42 + 0.118 * t.length, h = 0.30;
      sl.addShape(ST.roundRect, { x, y, w, h, rectRadius: 0.15, fill: { color: T.accent } });
      sl.addText(t, { x, y, w, h, fontFace: T.mono, fontSize: 9, bold: true, color: T.accentInk, charSpacing: 2, align: 'center', valign: 'middle', wrap: false });
      return w;
    };
    // Organic corner blobs — the MongoDB motif, approximated with large-radius roundRects + ellipses
    // that bleed off-edge. Editable vector in the .pptx. mode: 'cover' (accent on dark) | 'light'.
    const blobs = (sl, mode) => {
      if (mode === 'cover') {
        sl.addShape(ST.roundRect, { x: 9.7, y: 4.55, w: 5.6, h: 4.4, rectRadius: 1.9, fill: { color: T.accent, transparency: 82 } });
        sl.addShape(ST.ellipse, { x: 11.0, y: -1.5, w: 4.4, h: 4.4, fill: { color: T.accent, transparency: 90 } });
        sl.addShape(ST.roundRect, { x: 12.35, y: 0.15, w: 3.0, h: 2.6, rectRadius: 1.1, fill: { color: T.panel, transparency: 35 } });
      } else {
        sl.addShape(ST.roundRect, { x: 10.9, y: -1.4, w: 4.4, h: 4.0, rectRadius: 1.6, fill: { color: T.softBg } });
        sl.addShape(ST.ellipse, { x: 12.6, y: 1.7, w: 2.2, h: 2.2, fill: { color: T.accent, transparency: 90 } });
      }
    };
    // Small logo/leaf top-right. onDark → white logo; light slide → dark/native logo. Omitted if absent.
    const mark = (sl, onDark) => {
      const data = onDark ? L.white : (L.dark || L.white);
      if (data) sl.addImage({ data: String(data).replace(/^data:/, ''), x: 12.05, y: 0.30, sizing: { type: 'contain', w: 0.95, h: 0.42 } });
    };
    const chip = (sl, x, y, key) => {
      const label = catLabel(key); if (!label) return 0;
      const w = 0.30 + 0.100 * label.length;
      sl.addShape(ST.roundRect, { x, y, w, h: 0.22, rectRadius: 0.05, fill: { color: T.softBg }, line: { color: T.line, width: 0.75 } });
      sl.addText(label, { x, y, w, h: 0.22, fontFace: T.sans, fontSize: 8, bold: true, color: T.ink, charSpacing: 1, align: 'center', valign: 'middle', wrap: false });
      return w;
    };
    const card = (sl, o) => {
      sl.addShape(ST.roundRect, { x: o.x, y: o.y, w: o.w, h: o.h, rectRadius: 0.06, fill: { color: T.card }, line: { color: T.line, width: 1 } });
      if (o.edge) sl.addShape(ST.rect, { x: o.x, y: o.y + 0.05, w: 0.055, h: o.h - 0.10, fill: { color: o.edge } });
    };
    const noteCard = (sl, msg) => {
      card(sl, { x: 0.55, y: 2.7, w: 12.23, h: 1.2 });
      sl.addText(msg, { x: 0.55, y: 2.7, w: 12.23, h: 1.2, fontFace: T.sans, fontSize: 12, color: T.mute, align: 'center', valign: 'middle' });
    };
    // light-slide chrome: bg + soft blobs + logo + eyebrow pill + big SERIF title + accent rule
    const lightChrome = (sl, kicker, title) => {
      sl.background = { color: T.lightBg };
      blobs(sl, 'light'); mark(sl, false);
      sl.addText(brandLine.toUpperCase(), { x: 0.55, y: 0.34, w: 8, h: 0.24, fontFace: T.mono, fontSize: 8.5, bold: true, color: T.mute, charSpacing: 1.5, align: 'left', valign: 'middle' });
      pill(sl, 0.55, 0.74, kicker);
      sl.addText(title, { x: 0.53, y: 1.16, w: 9.4, h: 0.68, fontFace: T.serif, fontSize: 30, bold: true, color: T.ink, align: 'left', valign: 'middle' });
      sl.addShape(ST.line, { x: 0.57, y: 1.86, w: 0.7, h: 0, line: { color: T.accent, width: 2.25 } });
    };
    const footer = (sl, pageLabel) => {
      sl.addShape(ST.line, { x: 0.55, y: 7.02, w: 12.23, h: 0, line: { color: T.line, width: 1 } });
      sl.addText(`Prepared by ${T.agency} · Confidential   ·   Campaign: ${ctx.campaign || '—'}   ·   Regions: ${regions}   ·   Flight: ${win.start || '—'} → ${win.end || '—'}   ·   Data through: ${dataThrough}`,
        { x: 0.55, y: 7.08, w: 9.6, h: 0.34, fontFace: T.sans, fontSize: 7, color: T.mute, align: 'left', valign: 'top', wrap: true });
      sl.addText(pageLabel, { x: 10.2, y: 7.08, w: 2.58, h: 0.34, fontFace: T.sans, fontSize: 7, color: T.mute, align: 'right', valign: 'top' });
    };

    // ── SLIDE 1 — COVER (dark) ─────────────────────────────────────────────────────────────────
    const cov = pres.addSlide();
    cov.background = { color: T.bg };
    blobs(cov, 'cover');
    if (L.white) cov.addImage({ data: String(L.white).replace(/^data:/, ''), x: 0.85, y: 0.72, sizing: { type: 'contain', w: 2.6, h: 0.66 } });
    else cov.addText(clientName, { x: 0.85, y: 0.64, w: 6, h: 0.72, fontFace: T.serif, fontSize: 30, bold: true, color: T.onDark, align: 'left', valign: 'middle' });
    cov.addText(brandLine.toUpperCase(), { x: 8.55, y: 0.78, w: 3.2, h: 0.24, fontFace: T.mono, fontSize: 8.5, bold: true, color: T.onDarkMute, charSpacing: 1.5, align: 'right', valign: 'middle' });
    pill(cov, 0.85, 1.85, 'Campaign Performance Report');
    cov.addText(clamp(R.headline || `${clientName} - ${ctx.campaign || ''}`, 140), {
      x: 0.83, y: 2.42, w: 11.4, h: 2.1, fontFace: T.serif, fontSize: 36, bold: true, color: T.onDark, align: 'left', valign: 'top', fit: 'shrink', wrap: true,
    });
    // three info chips (flight · duration · regions)
    [{ lbl: 'FLIGHT WINDOW', val: `${win.start || '—'} → ${win.end || '—'}` },
     { lbl: 'DURATION', val: `${win.days != null ? win.days : '—'} days` },
     { lbl: 'REGIONS', val: clamp(regions, 22) }].forEach((c, i) => {
      const x = 0.85 + i * 3.78;
      cov.addShape(ST.roundRect, { x, y: 4.9, w: 3.58, h: 0.95, rectRadius: 0.08, fill: { color: T.panel } });
      if (i === 0) cov.addShape(ST.rect, { x, y: 4.94, w: 0.05, h: 0.87, fill: { color: T.accent } });
      cov.addText(c.lbl, { x: x + 0.16, y: 5.0, w: 3.24, h: 0.2, fontFace: T.mono, fontSize: 7.5, bold: true, color: T.onDarkMute, charSpacing: 1.5, align: 'left', valign: 'top' });
      cov.addText(c.val, { x: x + 0.16, y: 5.26, w: 3.28, h: 0.5, fontFace: T.sans, fontSize: 15, bold: true, color: T.onDark, align: 'left', valign: 'top', fit: 'shrink', wrap: false });
    });
    cov.addText(`Generated ${fmtDate(ctx.generated_at)} · Data through ${dataThrough} UTC`, { x: 0.85, y: 6.15, w: 8, h: 0.3, fontFace: T.sans, fontSize: 9, color: T.onDarkMute, align: 'left', valign: 'middle' });
    cov.addShape(ST.line, { x: 0.85, y: 6.75, w: 11.63, h: 0, line: { color: T.onDarkMute, width: 0.5, transparency: 55 } });
    cov.addText(`Prepared by ${T.agency} · Confidential`, { x: 0.85, y: 6.9, w: 6, h: 0.3, fontFace: T.sans, fontSize: 9, bold: true, color: T.onDark, align: 'left', valign: 'top' });
    cov.addText(`Figures pulled live from source data. Analysis & recommendations generated by ${modelLabel} with live web research - review before circulation.`,
      { x: 7.0, y: 6.87, w: 5.48, h: 0.5, fontFace: T.sans, fontSize: 7, color: T.onDarkMute, align: 'right', valign: 'top', wrap: true });

    // ── SLIDE 2 — What happened? (slide1) ───────────────────────────────────────────────────────
    const s2 = pres.addSlide();
    lightChrome(s2, '01 · What happened', 'What happened?');
    footer(s2, 'What happened · 2 / 4');
    { const st = STATUS[R.overall_status] || STATUS.neutral;
      s2.addShape(ST.roundRect, { x: 9.55, y: 1.18, w: 3.23, h: 0.34, rectRadius: 0.13, fill: { color: T.lightBg }, line: { color: st.hex, width: 1 } });
      s2.addShape(ST.ellipse, { x: 9.73, y: 1.295, w: 0.11, h: 0.11, fill: { color: st.hex } });
      s2.addText(st.label, { x: 9.95, y: 1.18, w: 2.7, h: 0.34, fontFace: T.sans, fontSize: 10, bold: true, color: st.hex, align: 'left', valign: 'middle' });
    }
    if (R.campaign_type) s2.addText(`${R.campaign_type}`.toUpperCase(), { x: 6.9, y: 1.18, w: 2.5, h: 0.34, fontFace: T.sans, fontSize: 8, bold: true, color: T.mute, charSpacing: 1.5, align: 'right', valign: 'middle' });
    { const sumRuns = [{ text: clamp(S1.summary, 210), options: { color: T.ink } }];
      if (R.confidence_note) sumRuns.push({ text: '  ' + clamp(R.confidence_note, 130), options: { italic: true, color: T.mute, breakLine: true } });
      s2.addText(sumRuns, { x: 0.55, y: 2.02, w: 12.23, h: 0.66, fontFace: T.sans, fontSize: 12, align: 'left', valign: 'top', isTextBox: true, wrap: true, fit: 'shrink' });
    }
    if (!kpis.length) noteCard(s2, 'No KPI highlights were returned for this view.');
    else {
      // Grid of KPI cards, height-capped + vertically centered so a few cards don't stretch into
      // tall near-empty boxes (Google Slides ignores autofit, so we also size the value to the string).
      const n = kpis.length, g = 0.20, cols = n <= 4 ? n : 3, rws = Math.ceil(n / cols);
      const bandTop = 2.82, bandH = 3.58, capH = 1.98;
      const cardW = (12.23 - g * (cols - 1)) / cols;
      let cardH = (bandH - g * (rws - 1)) / rws; if (cardH > capH) cardH = capH;
      const gridH = cardH * rws + g * (rws - 1), yTop = bandTop + Math.max(0, (bandH - gridH) / 2);
      const valSize = cols <= 2 ? 30 : (cols === 3 ? 25 : 27);
      kpis.forEach((k, i) => {
        const col = i % cols, row = Math.floor(i / cols), x = 0.55 + col * (cardW + g), y = yTop + row * (cardH + g);
        card(s2, { x, y, w: cardW, h: cardH, edge: (STATUS[k.status] || STATUS.neutral).hex });
        chip(s2, x + 0.16, y + 0.15, catOf(k));
        s2.addText(clamp(k.label, 26).toUpperCase(), { x: x + 0.16, y: y + 0.46, w: cardW - 0.32, h: 0.20, fontFace: T.sans, fontSize: 8, bold: true, color: T.mute, charSpacing: 1.5, align: 'left', valign: 'middle', fit: 'shrink' });
        const vstr = clamp(k.value, 18);
        const vS = Math.max(15, Math.min(valSize, Math.floor((cardW - 0.34) / (Math.max(vstr.length, 1) * 0.0072))));
        s2.addText(vstr, { x: x + 0.16, y: y + 0.68, w: cardW - 0.32, h: 0.5, fontFace: T.serif, fontSize: vS, bold: true, color: T.ink, align: 'left', valign: 'middle', fit: 'shrink', wrap: false });
        s2.addText(clamp(k.detail, 84), { x: x + 0.16, y: y + 1.20, w: cardW - 0.32, h: Math.max(0.4, cardH - 1.30), fontFace: T.sans, fontSize: 10, color: T.mute, align: 'left', valign: 'top', isTextBox: true, wrap: true, fit: 'shrink' });
      });
    }

    // ── SLIDE 3 — Why did it happen? (slide2) ─────────────────────────────────────────────────────
    const s3 = pres.addSlide();
    lightChrome(s3, '02 · Why', 'Why did it happen?');
    footer(s3, 'Why it happened · 3 / 4');
    if (S2.summary) s3.addText(clamp(S2.summary, 210), { x: 0.55, y: 2.02, w: 12.23, h: 0.5, fontFace: T.sans, fontSize: 12, color: T.ink, align: 'left', valign: 'top', isTextBox: true, wrap: true, fit: 'shrink' });
    if (!drivers.length) noteCard(s3, 'No drivers were identified for this view.');
    else {
      // Row height capped + stack vertically centered so 1-2 drivers don't balloon into huge rows.
      const bandTop = 2.62, H = (sources.length ? 3.78 : 4.34), n = drivers.length, g = 0.14, capH = 1.5;
      let rowH = (H - g * (n - 1)) / n; if (rowH > capH) rowH = capH;
      const stackH = rowH * n + g * (n - 1), y0 = bandTop + Math.max(0, (H - stackH) / 2);
      drivers.forEach((d, i) => {
        const y = y0 + i * (rowH + g), dir = DIR[d.direction] || DIR.flat;
        card(s3, { x: 0.55, y, w: 12.23, h: rowH, edge: dir.hex });
        s3.addShape(ST.roundRect, { x: 0.69, y: y + 0.12, w: 0.34, h: 0.34, rectRadius: 0.05, fill: { color: T.bg } });
        s3.addText(String(i + 1), { x: 0.69, y: y + 0.12, w: 0.34, h: 0.34, fontFace: T.sans, fontSize: 13, bold: true, color: T.onDark, align: 'center', valign: 'middle' });
        s3.addText(dir.g, { x: 1.10, y: y + 0.12, w: 0.34, h: 0.34, fontFace: T.sans, fontSize: 13, bold: true, color: dir.hex, align: 'center', valign: 'middle' });
        s3.addText(clamp(d.title, 64), { x: 1.55, y: y + 0.12, w: 6.4, h: 0.3, fontFace: T.sans, fontSize: 12, bold: true, color: T.ink, align: 'left', valign: 'middle', fit: 'shrink' });
        chip(s3, 8.1, y + 0.13, catOf(d));
        if (CONF[d.confidence]) s3.addText(CONF[d.confidence], { x: 9.7, y: y + 0.13, w: 3.0, h: 0.26, fontFace: T.sans, fontSize: 8, color: T.mute, charSpacing: 1, align: 'right', valign: 'middle' });
        const expl = [{ text: clamp(d.explanation, 230), options: { color: T.ink } }];
        const si = d.source_index;
        if (Number.isInteger(si) && si >= 0 && si < sources.length) expl.push({ text: ` [${si + 1}]`, options: { bold: true, color: T.mute, superscript: true, fontSize: 8 } });
        s3.addText(expl, { x: 1.55, y: y + 0.46, w: 11.0, h: rowH - 0.78, fontFace: T.sans, fontSize: 10.5, align: 'left', valign: 'top', isTextBox: true, wrap: true, fit: 'shrink' });
        if (d.evidence && rowH >= 0.85) s3.addText([
          { text: 'EVIDENCE  ', options: { bold: true, color: T.mute, charSpacing: 1, fontSize: 8 } },
          { text: clamp(d.evidence, 110), options: { color: T.ink, fontSize: 9 } },
        ], { x: 1.55, y: y + rowH - 0.30, w: 11.0, h: 0.24, fontFace: T.sans, align: 'left', valign: 'middle', fit: 'shrink' });
      });
      if (sources.length) {
        s3.addShape(ST.line, { x: 0.55, y: 6.42, w: 12.23, h: 0, line: { color: T.line, width: 0.75 } });
        s3.addText('SOURCES', { x: 0.55, y: 6.46, w: 1.2, h: 0.3, fontFace: T.sans, fontSize: 7, bold: true, color: T.mute, charSpacing: 1.5, align: 'left', valign: 'top' });
        const runs = [];
        sources.slice(0, 10).forEach((s, i) => {
          const safe = /^https?:\/\//i.test(s.url || '');
          runs.push({ text: `[${i + 1}] `, options: { bold: true, color: T.mute } });
          runs.push({ text: clamp(s.title, 42) + (i < Math.min(sources.length, 10) - 1 ? '   ' : ''), options: { color: T.mute, underline: safe ? { style: 'sng' } : undefined, hyperlink: safe ? { url: s.url, tooltip: s.title } : undefined } });
        });
        s3.addText(runs, { x: 1.85, y: 6.46, w: 10.9, h: 0.5, fontFace: T.sans, fontSize: 7, align: 'left', valign: 'top', isTextBox: true, wrap: true, fit: 'shrink' });
      }
    }

    // ── SLIDE 4 — What should we do? (slide3) ─────────────────────────────────────────────────────
    const s4 = pres.addSlide();
    lightChrome(s4, '03 · Recommended actions', 'What should we do?');
    footer(s4, 'Recommended actions · 4 / 4');
    if (S3.summary) s4.addText(clamp(S3.summary, 210), { x: 0.55, y: 2.02, w: 12.23, h: 0.5, fontFace: T.sans, fontSize: 12, color: T.ink, align: 'left', valign: 'top', isTextBox: true, wrap: true, fit: 'shrink' });
    if (!actions.length) noteCard(s4, 'No recommendations were generated for this view.');
    else {
      // Row height capped + stack vertically centered so a short action list stays compact, not stretched.
      const bandTop = 2.62, H = 4.34, n = actions.length, g = 0.16, capH = 1.55;
      let rowH = (H - g * (n - 1)) / n; if (rowH > capH) rowH = capH;
      const stackH = rowH * n + g * (n - 1), y0 = bandTop + Math.max(0, (H - stackH) / 2);
      actions.forEach((a, i) => {
        const y = y0 + i * (rowH + g), p = PRI[a.priority] || PRI.low;
        card(s4, { x: 0.55, y, w: 12.23, h: rowH, edge: p.hex });
        s4.addShape(ST.roundRect, { x: 0.69, y: y + 0.14, w: 0.40, h: 0.40, rectRadius: 0.05, fill: { color: p.hex } });
        s4.addText(String(i + 1), { x: 0.69, y: y + 0.14, w: 0.40, h: 0.40, fontFace: T.sans, fontSize: 15, bold: true, color: 'FFFFFF', align: 'center', valign: 'middle' });
        s4.addText(clamp(a.title, 70), { x: 1.25, y: y + 0.13, w: 6.6, h: 0.3, fontFace: T.sans, fontSize: 12, bold: true, color: T.ink, align: 'left', valign: 'middle', fit: 'shrink' });
        s4.addShape(ST.roundRect, { x: 8.0, y: y + 0.14, w: 1.55, h: 0.28, rectRadius: 0.1, fill: { color: T.lightBg }, line: { color: p.hex, width: 1 } });
        s4.addText(p.label, { x: 8.0, y: y + 0.14, w: 1.55, h: 0.28, fontFace: T.sans, fontSize: 8, bold: true, color: p.hex, charSpacing: 1, align: 'center', valign: 'middle' });
        chip(s4, 9.7, y + 0.15, catOf(a));
        if (EFFORT[a.effort]) s4.addText(EFFORT[a.effort], { x: 11.2, y: y + 0.14, w: 1.55, h: 0.28, fontFace: T.sans, fontSize: 8, color: T.mute, charSpacing: 0.5, align: 'right', valign: 'middle' });
        s4.addText(clamp(a.rationale, 200), { x: 1.25, y: y + 0.50, w: 11.5, h: rowH - 0.62, fontFace: T.sans, fontSize: 10.5, color: T.ink, align: 'left', valign: 'top', isTextBox: true, wrap: true, fit: 'shrink' });
      });
    }

    const campSlug = String(ctx.campaign || 'Campaign').replace(/[^\w]+/g, '_').replace(/^_|_$/g, '');
    const day = String(win.end || (ctx.generated_at || '')).slice(0, 10) || 'report';
    const fileName = `${T.filePrefix || clientName.replace(/[^\w]+/g, '_')}_${campSlug}_${day}.pptx`.replace(/_+/g, '_');
    // download:false -> return {blob, fileName} so the caller (the portal, via postMessage) downloads in the
    // TOP frame - more robust than a download initiated inside a hidden iframe.
    if (opts && opts.download === false) return { blob: await pres.write({ outputType: 'blob', compression: true }), fileName };
    await pres.writeFile({ fileName, compression: true });
    return { blob: null, fileName };
  };
})(typeof window !== 'undefined' ? window : this);
