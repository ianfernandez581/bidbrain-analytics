
<script>
/* BB LOGIN KIT v1 - the three behavioural bits. Canonical source scripts/motion_kit/.
   Everything here degrades to the plain form if any of it is missing: the input, the button and
   the POST are untouched, so a login can never fail because of this script. */
(function(){
  var form = document.querySelector('form[action="/login"]') || document.querySelector('form');
  var pw   = document.querySelector('.bb-pw input') ||
             document.querySelector('input[name="password"]');
  var togg = document.querySelector('.bb-pw-t');
  var caps = document.querySelector('.bb-caps');
  var btn  = form && (form.querySelector('button[type="submit"]') || form.querySelector('button'));

  /* 1. show / hide. Type is flipped in place, so the field keeps its value, its name and its
        position in the tab order; the caret is put back where the user was. */
  if (togg && pw){
    togg.addEventListener('click', function(){
      var hidden = pw.type === 'password';
      var at = pw.value.length;
      pw.type = hidden ? 'text' : 'password';
      togg.textContent = hidden ? 'Hide' : 'Show';
      togg.setAttribute('aria-label', (hidden ? 'Hide' : 'Show') + ' password');
      pw.focus();
      try { pw.setSelectionRange(at, at); } catch(e){}
    });
  }

  /* 2. Caps Lock. getModifierState is only meaningful on a real key event, so it is read on the
        field's own keys - no global listener, nothing polled.
        The TEXT is written here rather than sitting in the markup: the element is a live region,
        and a permanent "Caps Lock is on" string would be read out by a screen reader whenever the
        form is traversed, whether it is on or not. Empty when off, filled when on - which is also
        what makes role=status announce it at the right moment. */
  if (caps && pw){
    var CAPS_MSG = 'Caps Lock is on';
    var set = function(on){
      if (caps.classList.contains('on') === on) return;
      caps.classList.toggle('on', on);
      caps.textContent = on ? CAPS_MSG : '';
    };
    var check = function(e){
      if (typeof e.getModifierState !== 'function') return;
      set(e.getModifierState('CapsLock'));
    };
    pw.addEventListener('keydown', check);
    pw.addEventListener('keyup', check);
    pw.addEventListener('blur', function(){ set(false); });
  }

  /* 3. Submit state. The disable happens on the NEXT tick, after the browser has already started
        the POST, so it stops a second submission without ever blocking the first. Only the label
        of a plain text button is swapped - a button with markup inside (an arrow, an icon) keeps
        its contents.
        The `pageshow` reset is NOT optional: log in, then press Back, and the browser restores
        this page from its cache exactly as it was - disabled button, "Checking..." still on it -
        which would strand someone on a login form they cannot submit. pageshow fires on every
        restore, so the control is always live again. */
  if (form && btn){
    var label0 = btn.textContent;
    form.addEventListener('submit', function(){
      setTimeout(function(){
        btn.disabled = true;
        if (!btn.children.length) btn.textContent = 'Checking...';
      }, 0);
    });
    window.addEventListener('pageshow', function(){
      btn.disabled = false;
      if (!btn.children.length) btn.textContent = label0;
    });
  }

  /* 4. A server-rendered error announces itself once. */
  var err = document.querySelector('.err');
  if (err && err.textContent.trim()) err.classList.add('bb-shake');
})();
</script>
