/*
 * src/brain/client-colors.js  —  stable per-client colour for the Brain tab
 * ----------------------------------------------------------------------------
 * getClientColor(clientId) -> { bg, fg, border } (HSL strings).
 * A stable string hash of the client id picks one of 8 pre-defined hue slots,
 * so a given client always draws the same colour everywhere in the tab.
 *
 * The 8 hues are spaced around the wheel and chosen to stay legible on The
 * Grid's dark-default surface AND its light theme. Pass the current theme
 * ('dark' | 'light') — or leave it out and we read data-theme off <html>.
 *
 * UMD: Node -> module.exports, browser -> window.BrainColors.
 */
(function (root, factory) {
  var api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (typeof window !== 'undefined') window.BrainColors = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  // 8 distinct hues (degrees). Enough for the 8 live clients, one each.
  var HUES = [210, 265, 330, 15, 40, 150, 185, 95]; // blue, violet, pink, red-orange, amber, green, teal, lime

  // The 8 live clients are pinned to distinct slots so no two ever collide.
  // (A plain hash%8 would clash — verified.) Unknown ids fall back to the hash.
  var SLOT = { resetdata: 0, mongodb: 1, cloudflare: 2, schneider: 3, vmch: 4, tlm: 5, proptrack: 6, hireright: 7 };

  function hashStr(s) {
    var h = 2166136261;
    s = String(s == null ? '' : s);
    for (var i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 16777619); }
    return h >>> 0;
  }
  function slotFor(clientId) {
    return SLOT.hasOwnProperty(clientId) ? SLOT[clientId] : (hashStr(clientId) % HUES.length);
  }

  function currentTheme(theme) {
    if (theme === 'dark' || theme === 'light') return theme;
    try {
      var t = document.documentElement.getAttribute('data-theme');
      if (t === 'light' || t === 'dark') return t;
    } catch (e) { /* Node / no DOM */ }
    return 'dark';
  }

  function getClientColor(clientId, theme) {
    var hue = HUES[slotFor(clientId)];
    if (currentTheme(theme) === 'light') {
      // soft tinted chip on white surfaces
      return {
        bg: 'hsl(' + hue + ' 82% 94%)',
        fg: 'hsl(' + hue + ' 62% 34%)',
        border: 'hsl(' + hue + ' 55% 82%)'
      };
    }
    // translucent tinted chip on near-black surfaces
    return {
      bg: 'hsl(' + hue + ' 55% 60% / 0.16)',
      fg: 'hsl(' + hue + ' 78% 74%)',
      border: 'hsl(' + hue + ' 55% 60% / 0.34)'
    };
  }

  return { getClientColor: getClientColor, HUES: HUES };
});
