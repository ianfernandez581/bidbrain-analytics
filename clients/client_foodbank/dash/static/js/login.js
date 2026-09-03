/* Foodbank login - behaviour. Source of truth: clients/client_foodbank/design/login_reference.html
   (sync by overwriting). The only change from the reference is that the inert demo `attempt()` is
   gone: the card is a real <form> posting to the Cloudflare-style /login route, so Enter and the
   button submit natively, and a rejected password comes back server-rendered with the error already
   visible (class "on" on #err) - this script then shakes the card once. */
(function () {
  /* ---------------------------------------------------------------
     Countdown: 3,500,000 -> 0 over 8s.
     Eased so it moves quickly through the millions and lands gently
     on zero. DURATION is the only speed knob.
     Set LOOP = true to restart every REST_MS after it lands.
  ----------------------------------------------------------------*/
  const START = 3_500_000, DURATION = 8_000, LOOP = false, REST_MS = 30_000;
  const reduce = matchMedia('(prefers-reduced-motion: reduce)').matches;

  const numEl = document.getElementById('num');
  const resolveEl = document.getElementById('resolve');
  const fmt = new Intl.NumberFormat('en-AU');

  // slow -> fast -> slow, weighted to end gently
  const ease = t => t < .5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2;

  let raf, t0;
  function frame(now) {
    if (!t0) t0 = now;
    const p = Math.min((now - t0) / DURATION, 1);
    const value = Math.round(START * (1 - ease(p)));

    numEl.textContent = fmt.format(value);

    if (p < 1) { raf = requestAnimationFrame(frame); }
    else { land(); }
  }

  function land() {
    numEl.textContent = '0';
    numEl.classList.add('zero');
    resolveEl.classList.add('on');
    if (LOOP) setTimeout(start, REST_MS);
  }

  function start() {
    cancelAnimationFrame(raf);
    t0 = null;
    numEl.classList.remove('zero');
    resolveEl.classList.remove('on');
    raf = requestAnimationFrame(frame);
  }

  if (numEl && resolveEl) {
    if (reduce) { land(); }
    else { start(); }
    numEl.addEventListener('click', () => { if (!reduce) start(); });
  }

  /* ---- login card behaviour ---- */
  const pw = document.getElementById('pw'), err = document.getElementById('err');
  const toggle = document.getElementById('toggle');
  const card = pw && pw.closest('.card');
  if (toggle && pw) {
    toggle.addEventListener('click', e => {
      const show = pw.type === 'password';
      pw.type = show ? 'text' : 'password';
      e.target.textContent = show ? 'Hide' : 'Show';
      e.target.setAttribute('aria-label', (show ? 'Hide' : 'Show') + ' password');
      pw.focus();
    });
  }
  if (pw && err) pw.addEventListener('input', () => err.classList.remove('on'));
  // a server-rendered rejection arrives with the error already on: shake once so it registers
  if (card && err && err.classList.contains('on')) {
    card.classList.add('shake');
    setTimeout(() => card.classList.remove('shake'), 420);
  }
})();
