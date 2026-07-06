/*
 * src/brain/toast.js  —  minimal bottom-right toast for the Brain tab
 * ----------------------------------------------------------------------------
 * toast.success(message) / toast.error(message). 4s auto-dismiss, stacks,
 * click to dismiss early. Uses The Grid's CSS variables so it themes with the
 * app. Styling lives in the .bt-toast* rules injected into the-grid.html.
 *
 * UMD: browser -> window.toast (and window.BrainToast). No-op in Node.
 */
(function (root, factory) {
  var api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (typeof window !== 'undefined') { window.toast = api; window.BrainToast = api; }
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  var ICONS = {
    success: '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5"/></svg>',
    error: '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/><path d="M12 8v5M12 16.5v.01"/></svg>'
  };

  function host() {
    if (typeof document === 'undefined') return null;
    var el = document.getElementById('bt-toast-host');
    if (!el) { el = document.createElement('div'); el.id = 'bt-toast-host'; el.className = 'bt-toast-host'; document.body.appendChild(el); }
    return el;
  }

  function show(kind, message) {
    var h = host();
    if (!h) return; // Node / no DOM
    var t = document.createElement('div');
    t.className = 'bt-toast bt-toast-' + kind;
    t.setAttribute('role', 'status');
    t.innerHTML = '<span class="bt-toast-i">' + (ICONS[kind] || '') + '</span><span class="bt-toast-m"></span>';
    t.querySelector('.bt-toast-m').textContent = String(message == null ? '' : message);
    h.appendChild(t);
    // enter
    requestAnimationFrame(function () { t.classList.add('in'); });
    var killed = false;
    function kill() { if (killed) return; killed = true; t.classList.remove('in'); setTimeout(function () { if (t.parentNode) t.parentNode.removeChild(t); }, 220); }
    t.addEventListener('click', kill);
    setTimeout(kill, 4000);
    return t;
  }

  return {
    success: function (m) { return show('success', m); },
    error: function (m) { return show('error', m); }
  };
});
