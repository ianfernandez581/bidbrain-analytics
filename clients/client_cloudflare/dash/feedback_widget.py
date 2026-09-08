"""Feedback pill for DIRECT logins to the Cloudflare dashboard (vendored from the platform).

Why this exists: the platform front-door (dashboards.bidbrain.ai) injects a Feedback pill into
every dashboard it reverse-proxies (bidbrain-platform/dash/main.py `_FEEDBACK_WIDGET`). Cloudflare's
own people largely reach THIS service directly on its run.app URL - their office network does not
resolve dashboards.bidbrain.ai - and a direct hit never passes through that proxy, so they had no
way to send feedback at all. This module gives the service its own pill plus the POST route behind
it, so the client company can file notes from whichever door they came in by.

Storage is the PLATFORM's private bucket, in the platform's own record shape, so a note filed here
appears in the existing tracker at dashboards.bidbrain.ai/feedback/admin - and gets the same AI
transcription/summary pass - with NO platform-side change. The canonical field list and the
`feedback/<client>/...` object layout live in bidbrain-platform/dash/feedback.py: that file is the
source of truth, keep this one in step with it.

Config: env PLATFORM_BUCKET (the platform's bucket, `bidbrain-analytics-platform-dash`). Unset =>
the whole feature is INERT - no pill is injected and the route 503s - so a service that has not had
enable_feedback_cloudflare.ps1 run against it can never show a button that fails.
"""
import os
import json
import time
import uuid

_PREFIX = "feedback"                    # must match bidbrain-platform/dash/feedback.py
MAX_AUDIO_BYTES = 16 * 1024 * 1024      # widget caps recording at 2 min (opus is tiny)
MAX_IMAGE_BYTES = 8 * 1024 * 1024       # a JPEG viewport screenshot is normally well under 1 MB
MAX_TEXT_CHARS = 8000

# MediaRecorder picks a container per browser (Chrome: audio/webm, Safari: audio/mp4). Map the mime
# to a sane extension so the stored object is directly playable in the tracker's <audio> tag.
_EXT = {"audio/webm": "webm", "audio/ogg": "ogg", "audio/mp4": "m4a",
        "audio/mpeg": "mp3", "audio/wav": "wav", "audio/x-wav": "wav"}

_client = None


def bucket_name():
    return (os.environ.get("PLATFORM_BUCKET") or "").strip()


def enabled():
    """False until the platform bucket is configured on this service (see the module docstring)."""
    return bool(bucket_name())


def _bucket():
    """Lazy, cached storage client - keeps the import off the no-op path."""
    global _client
    if _client is None:
        from google.cloud import storage
        _client = storage.Client()
    return _client.bucket(bucket_name())


def _ext_for(ctype):
    return _EXT.get((ctype or "").split(";")[0].strip().lower(), "webm")


def save(client, text, audio_bytes, audio_ctype, page, user_kind, screenshot_bytes=None,
         reporter="", deadline=""):
    """Persist one feedback entry to the platform bucket. Binary objects are written FIRST, then the
    JSON that references them, so a half-written entry never dangles in the tracker."""
    text = (text or "").strip()[:MAX_TEXT_CHARS]
    rid = f"{int(time.time())}-{uuid.uuid4().hex[:8]}"
    bucket = _bucket()

    audio_name = ""
    if audio_bytes:
        audio_name = f"{rid}.{_ext_for(audio_ctype)}"
        b = bucket.blob(f"{_PREFIX}/{client}/{audio_name}")
        b.cache_control = "no-store"
        b.upload_from_string(audio_bytes, content_type=(audio_ctype or "audio/webm"))

    shot_name = ""
    if screenshot_bytes:
        shot_name = f"{rid}.jpg"
        b = bucket.blob(f"{_PREFIX}/{client}/{shot_name}")
        b.cache_control = "no-store"
        b.upload_from_string(screenshot_bytes, content_type="image/jpeg")

    rec = {"id": rid, "client": client, "text": text, "audio": audio_name, "screenshot": shot_name,
           "page": (page or "")[:300], "user_kind": user_kind or "", "created_at": int(time.time()),
           "reporter": (reporter or "").strip()[:120], "deadline": (deadline or "").strip()[:40]}
    j = bucket.blob(f"{_PREFIX}/{client}/{rid}.json")
    j.cache_control = "no-store"
    j.upload_from_string(json.dumps(rec, separators=(",", ":")), content_type="application/json")
    return rec


# --- the injected pill -----------------------------------------------------------------------
# Self-contained: fully scoped under #bbfbn-* (the platform's copy owns #bbfb-*, so the two can
# never collide even if both ever land on one page) and inline-styled, because it is bolted onto a
# themed page it knows nothing about. Styled to this dashboard's dark-glow orange skin rather than
# the platform's indigo, so it reads as part of the page the client is looking at.
#
# It MOUNTS ITSELF ONLY ON A DIRECT HIT. Behind the front-door the page is served under
# /d/<client>/ and the proxy appends its OWN widget after this script, so mounting there would give
# two pills; the path test is the primary guard and the #bbfb-btn probe is the belt-and-braces one
# (it is meaningful because the mount is deferred to DOMContentLoaded, by which point the proxy's
# appended tail has been parsed).
_WIDGET = """
<style>
#bbfbn-btn{position:fixed;bottom:18px;right:18px;z-index:2147483646;display:inline-flex;
 align-items:center;gap:7px;padding:10px 15px;border-radius:999px;border:1px solid rgba(255,255,255,.22);
 font:600 13px/1 system-ui,-apple-system,Segoe UI,Roboto,Arial,sans-serif;color:#fff;cursor:pointer;
 background:rgba(20,15,12,.88);box-shadow:0 2px 12px rgba(0,0,0,.42);backdrop-filter:blur(4px);
 -webkit-backdrop-filter:blur(4px)}
#bbfbn-btn:hover{border-color:rgba(243,128,32,.75)}
#bbfbn-panel{position:fixed;bottom:66px;right:18px;z-index:2147483646;width:330px;
 max-width:calc(100vw - 36px);display:none;flex-direction:column;gap:10px;padding:16px;
 border-radius:14px;background:#17120f;color:#f4f1ee;border:1px solid rgba(255,255,255,.14);
 box-shadow:0 12px 44px rgba(0,0,0,.55);
 font:14px/1.45 system-ui,-apple-system,Segoe UI,Roboto,Arial,sans-serif}
#bbfbn-panel.open{display:flex}
#bbfbn-panel h3{margin:0;font-size:15px;font-weight:700}
#bbfbn-panel p.sub{margin:0;font-size:12px;color:#a79f98}
#bbfbn-text{width:100%;min-height:84px;resize:vertical;padding:9px 10px;border-radius:9px;
 background:#0e0b09;color:#f4f1ee;border:1px solid rgba(255,255,255,.16);font:inherit;outline:none}
#bbfbn-name,#bbfbn-deadline{width:100%;padding:9px 10px;border-radius:9px;background:#0e0b09;
 color:#f4f1ee;border:1px solid rgba(255,255,255,.16);font:inherit;outline:none;color-scheme:dark}
#bbfbn-text:focus,#bbfbn-name:focus,#bbfbn-deadline:focus{border-color:#F38020}
.bbfbn-lbl{font-size:11px;color:#a79f98;margin:-2px 0 -5px}
#bbfbn-row{display:flex;align-items:center;gap:8px}
.bbfbn-mini{display:inline-flex;align-items:center;gap:6px;padding:8px 12px;border-radius:9px;
 cursor:pointer;font:600 13px/1 inherit;border:1px solid rgba(255,255,255,.18);background:#0e0b09;
 color:#f4f1ee}
.bbfbn-mini.rec{background:#7f1d1d;border-color:#ef4444}
#bbfbn-send{flex:1;justify-content:center;background:#F38020;border-color:#F38020;color:#fff}
#bbfbn-send:disabled{opacity:.5;cursor:default}
#bbfbn-status{font-size:12px;min-height:15px;color:#a79f98}
#bbfbn-audio{width:100%;display:none;margin-top:2px}
#bbfbn-dot{width:9px;height:9px;border-radius:50%;background:#ef4444;display:inline-block;
 animation:bbfbnpulse 1s infinite}
@keyframes bbfbnpulse{0%,100%{opacity:1}50%{opacity:.25}}
</style>
<script>(function(){
  var CLIENT='__CLIENT__';
  var MARKUP=
    "<button id='bbfbn-btn' type='button' aria-label='Send feedback'>"+
    "<svg width='15' height='15' viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2' "+
    "stroke-linecap='round' stroke-linejoin='round'>"+
    "<path d='M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z'></path></svg>"+
    "Feedback</button>"+
    "<div id='bbfbn-panel' role='dialog' aria-label='Send feedback'>"+
    "<h3>Send feedback</h3>"+
    "<p class='sub'>Type a note or record a voice message, whichever is easiest.</p>"+
    "<input id='bbfbn-name' type='text' placeholder='Your name (optional)' autocomplete='name'>"+
    "<textarea id='bbfbn-text' placeholder='What is working, what is confusing, what you would like to see...'></textarea>"+
    "<p class='bbfbn-lbl'>Preferred deadline (optional)</p>"+
    "<input id='bbfbn-deadline' type='date'>"+
    "<audio id='bbfbn-audio' controls></audio>"+
    "<div id='bbfbn-row'>"+
    "<button id='bbfbn-mic' type='button' class='bbfbn-mini'>\\ud83c\\udfa4 Record</button>"+
    "<button id='bbfbn-send' type='button' class='bbfbn-mini'>Send</button>"+
    "</div><div id='bbfbn-status'></div></div>";

  function mount(){
    // Behind the platform front-door the page lives at /d/<client>/ and the proxy injects its own
    // pill: stand down rather than draw a second one.
    if(location.pathname.indexOf('/d/')===0) return;
    if(document.getElementById('bbfb-btn')) return;
    if(document.getElementById('bbfbn-btn')) return;
    document.body.insertAdjacentHTML('beforeend', MARKUP);

    var el=function(i){return document.getElementById(i);};
    var btn=el('bbfbn-btn'),panel=el('bbfbn-panel'),ta=el('bbfbn-text'),mic=el('bbfbn-mic'),
        send=el('bbfbn-send'),status=el('bbfbn-status'),audioEl=el('bbfbn-audio'),
        nameEl=el('bbfbn-name'),dlEl=el('bbfbn-deadline');
    var rec=null,chunks=[],blob=null,ctype='',timer=null,secs=0,shot=null;

    // A typed note is NEVER lost. This service's session is a HARD 12h cap (see PERMANENT_SESSION_
    // LIFETIME in main.py), and recovering from an expired one means signing in again - so the draft
    // has to survive a reload of this tab, not just a failed fetch. Every access guarded: a browser
    // with site data blocked throws on the accessor itself.
    var DKEY='bbfbn.draft.'+CLIENT;
    function draftSave(){try{localStorage.setItem(DKEY,JSON.stringify(
      {t:ta.value||'',n:nameEl.value||'',d:dlEl.value||''}));}catch(e){}}
    function draftClear(){try{localStorage.removeItem(DKEY);}catch(e){}}
    function draftLoad(){try{var d=JSON.parse(localStorage.getItem(DKEY)||'null');if(!d)return;
      if(d.t)ta.value=d.t;if(d.n)nameEl.value=d.n;if(d.d)dlEl.value=d.d;}catch(e){}}
    draftLoad();
    ta.addEventListener('input',draftSave);nameEl.addEventListener('input',draftSave);
    dlEl.addEventListener('change',draftSave);

    // Signed-out state: flagged on the PILL (visible without opening the panel) with the way out -
    // a link to the sign-in page - right in the panel. A generic "could not send, try again" is what
    // made a client conclude the whole feature was broken: retrying cannot fix an auth failure.
    function signedOut(on){
      if(on){btn.style.borderColor='#f59e0b';btn.title='Sign-in expired';
        status.innerHTML="You are signed out - this tab's sign-in expired. "+
          "<a href='/' target='_blank' rel='noopener' style='color:#F38020'>Sign in again</a>"+
          ", then press Send. Your note is saved here.";}
      else{btn.style.borderColor='';btn.title='';}
    }

    // Probe on OPEN, not on Send: being told you are signed out before writing a paragraph is the
    // whole point. Best-effort - a failed probe never blocks the panel or the post.
    function probe(){fetch('/feedback/ping',{credentials:'same-origin',cache:'no-store'})
      .then(function(r){signedOut(r.status===401);}).catch(function(){});}

    btn.onclick=function(){
      var opening=!panel.classList.contains('open');
      panel.classList.toggle('open');
      if(opening){ta.focus();grabShot();probe();}
    };

    // Also probe PASSIVELY, so a tab that died overnight flags itself instead of looking healthy:
    // the dashboard's own 5-min data.json poll swallows its failure in a bare catch, so the pill is
    // the only place a stale tab can show it. On re-focus ("back from lunch") and every 10 min.
    document.addEventListener('visibilitychange',function(){if(!document.hidden)probe();});
    setInterval(probe,10*60*1000);
    probe();

    // Lazily pull html2canvas the first time the panel opens and snapshot the visible viewport as a
    // compact JPEG, with the widget hidden so it is not in the shot. Best-effort: any failure (no
    // network, a CORS-tainted canvas) just leaves shot=null and the note sends without an image.
    function loadH2C(){return new Promise(function(res){
      if(window.html2canvas)return res();
      var s=document.createElement('script');
      s.src='https://cdnjs.cloudflare.com/ajax/libs/html2canvas/1.4.1/html2canvas.min.js';
      s.onload=res;s.onerror=res;document.head.appendChild(s);});}
    function grabShot(){shot=null;loadH2C().then(function(){
      if(!window.html2canvas)return;
      var dB=btn.style.display,dP=panel.style.display;
      btn.style.display='none';panel.style.display='none';
      return window.html2canvas(document.body,{useCORS:true,logging:false,scale:1,
        x:window.scrollX,y:window.scrollY,width:window.innerWidth,height:window.innerHeight})
        .then(function(c){c.toBlob(function(b){shot=b;},'image/jpeg',0.82);})
        .catch(function(){}).finally(function(){btn.style.display=dB;panel.style.display=dP;});});}

    function stopRec(){if(rec&&rec.state!=='inactive')rec.stop();}
    function resetTimer(){clearInterval(timer);timer=null;secs=0;}

    mic.onclick=function(){
      if(rec&&rec.state==='recording'){stopRec();return;}
      if(!navigator.mediaDevices||!window.MediaRecorder){
        status.textContent='Voice recording is not supported in this browser - please type instead.';
        return;}
      navigator.mediaDevices.getUserMedia({audio:true}).then(function(stream){
        chunks=[];blob=null;rec=new MediaRecorder(stream);ctype=rec.mimeType||'audio/webm';
        rec.ondataavailable=function(e){if(e.data&&e.data.size)chunks.push(e.data);};
        rec.onstop=function(){
          stream.getTracks().forEach(function(t){t.stop();});
          blob=new Blob(chunks,{type:ctype});
          audioEl.src=URL.createObjectURL(blob);audioEl.style.display='block';
          mic.classList.remove('rec');mic.textContent='\\ud83c\\udfa4 Re-record';resetTimer();
          status.textContent='Voice note ready - add a note if you like, then Send.';};
        rec.start();mic.classList.add('rec');mic.innerHTML='<span id="bbfbn-dot"></span> Stop (0s)';
        secs=0;timer=setInterval(function(){secs++;
          mic.innerHTML='<span id="bbfbn-dot"></span> Stop ('+secs+'s)';
          if(secs>=120)stopRec();},1000);
        status.textContent='Recording... (max 2 min)';
      }).catch(function(){
        status.textContent='Microphone blocked - allow access or just type your feedback.';});
    };

    send.onclick=function(){
      var txt=(ta.value||'').trim();
      if(!txt&&!blob){status.textContent='Add a note or a voice message first.';return;}
      send.disabled=true;status.textContent='Sending...';
      var fd=new FormData();
      fd.append('client',CLIENT);fd.append('text',txt);fd.append('page',location.pathname);
      fd.append('reporter',(nameEl.value||'').trim());fd.append('deadline',dlEl.value||'');
      if(blob)fd.append('audio',blob,'voice.'+((ctype.indexOf('mp4')>-1)?'m4a':(ctype.indexOf('ogg')>-1)?'ogg':'webm'));
      if(shot)fd.append('screenshot',shot,'shot.jpg');
      // Report what actually went wrong. 401 => the recoverable signed-out path (draft kept, link to
      // sign in, then Send works); anything else => the server's own message, so a real fault is
      // never disguised as "try again".
      fetch('/feedback',{method:'POST',body:fd,credentials:'same-origin'}).then(function(r){
        if(r.status===401){signedOut(true);send.disabled=false;return;}
        if(!r.ok){return r.json().catch(function(){return null;}).then(function(j){
          status.textContent=(j&&j.error)?j.error
            :('Could not send (error '+r.status+') - please try again.');
          send.disabled=false;});}
        signedOut(false);draftClear();
        status.textContent='Thanks - your feedback was sent!';
        ta.value='';nameEl.value='';dlEl.value='';blob=null;chunks=[];shot=null;
        audioEl.style.display='none';mic.textContent='\\ud83c\\udfa4 Record';
        setTimeout(function(){panel.classList.remove('open');status.textContent='';
          send.disabled=false;},1600);
      }).catch(function(){
        status.textContent='Could not send - check your connection and try again. '+
          'Your note is saved here.';send.disabled=false;});
    };
  }

  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',mount);
  else mount();
})();</script>
"""


def widget(client):
    """The pill's HTML+JS for one client key, ready to splice in before </body>."""
    return _WIDGET.replace("__CLIENT__", client)
