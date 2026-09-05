"""Gmail alert emails for windsor-connections-probe.

Sends through the Gmail API with an OAuth user token stored in Secret Manager
(windsor-alerts-gmail-oauth) - the same mechanism as ingest/gmail_data_pull, with the
gmail.send scope only. Mint the token once with gen_gmail_token.py.

Three templates, all plain HTML with an inlined style so they read the same in Gmail and
Outlook: a STATE-CHANGE email (one per run that changed something), a morning DIGEST while
anything is still red, and an ESTIMATED-EXPIRY warning. Every email says what changed, what it
means for which client, and the exact next step - and links to the Grid tab for the full view.
"""
from __future__ import annotations

import base64
import json
from email.message import EmailMessage
from html import escape


# The Grid's light palette, spelled out because email cannot use CSS variables.
BG       = "#F8F7F3"   # warm off-white, the site's section ground
PANEL    = "#FFFFFF"   # card
PANEL2   = "#FAFAFA"   # inset
GRP      = "#F2F1EC"   # chip ground
LINE     = "#EAEAEA"   # border
LINE2    = "#F0EFEA"   # hairline
INK      = "#1E1810"   # headings, a warm near-black
INK2     = "#62615C"   # body
INK3     = "#8F8D85"   # faint
BRAND    = "#22B573"   # the logo and button green
BRAND_IN = "#12925A"   # darkened for link text; #22B573 on white is under 3:1

# Montserrat is the face 100.digital sets everything in, headings and body alike. Most
# clients block webfonts, so it sits in front of a stack that degrades cleanly rather than
# to Times.
DISPLAY = "Montserrat,'Segoe UI',Roboto,Helvetica,Arial,sans-serif"
BODYF   = "Montserrat,-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif"

STATE_LABEL = {"ok": "healthy", "frozen": "frozen", "quiet": "quiet", "not_granted": "not granted", "error": "error", "idle": "idle"}
STATE_COLOR = {"ok": "#0E9F6E", "frozen": "#B45309", "quiet": "#6F827A", "not_granted": "#D92D20", "error": "#4338CA", "idle": "#879089"}
STATE_MEANING = {
    "not_granted": "Windsor no longer holds this account. The loader skips it every night and the dashboard keeps serving the last data it landed.",
    "frozen": "Windsor still returns rows, but our loader is not landing them in BigQuery. The grant is fine; the pipeline is ours to fix.",
    "error": "The connector has answered with an error on consecutive probes.",
    "ok": "Granted and current in BigQuery.",
    "quiet": "Granted, but the platform reports no delivery for the window.",
    "idle": "Expected to be quiet.",
}


# soft ground + coloured text, the same pill the tab uses. White-on-solid read as a
# notification badge; this reads as a state.
STATE_SOFT = {"ok": "#E6F6EF", "frozen": "#FBF1E4", "quiet": "#EEF3F0",
              "not_granted": "#FCEBEA", "error": "#EEF0FF", "idle": "#EEF3F0"}


def _pill(state: str) -> str:
    c = STATE_COLOR.get(state, INK3)
    bg = STATE_SOFT.get(state, GRP)
    return (f'<span style="display:inline-block;padding:3px 10px;border-radius:20px;font-size:11px;'
            f'font-weight:700;letter-spacing:.01em;color:{c};background:{bg}">'
            f'{escape(STATE_LABEL.get(state, state)).upper()}</span>')


def _logo() -> str:
    """The 100% DIGITAL mark, drawn in HTML.

    Not an <img>: image blocking is on by default in most clients, and a brand mark that
    only some readers see is worse than none. A bordered table cell renders everywhere;
    Outlook drops the radius and keeps the rest.
    """
    return (f'<table cellpadding="0" cellspacing="0" border="0" role="presentation" '
            f'style="border-collapse:separate"><tr><td align="center" valign="middle" '
            f'width="66" height="46" style="width:66px;height:46px;border:2px solid {BRAND};'
            f'border-radius:5px;line-height:1;padding:0 4px">'
            f'<div style="font-family:{DISPLAY};font-size:17px;font-weight:600;color:{BRAND};'
            f'letter-spacing:-.2px;line-height:1.05">100%</div>'
            f'<div style="font-family:{DISPLAY};font-size:8px;font-weight:500;color:{BRAND};'
            f'letter-spacing:.15em;line-height:1.1;padding-top:2px">DIGITAL</div>'
            f'</td></tr></table>')


def _shell(title: str, intro: str, body: str, grid_url: str) -> str:
    """The full message. An outer table centres it in Outlook, which ignores margin:auto."""
    return f"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light only"><meta name="supported-color-schemes" content="light only">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Montserrat:wght@400;500;600;700&display=swap">
<title>{escape(title)}</title></head>
<body style="margin:0;padding:0;background:{BG};color:{INK};font-family:{BODYF};
  -webkit-font-smoothing:antialiased">
<table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%"
  style="background:{BG};border-collapse:collapse"><tr><td align="center" style="padding:26px 14px 40px">
<table role="presentation" cellpadding="0" cellspacing="0" border="0" width="600"
  style="width:600px;max-width:600px;border-collapse:collapse">

  <tr><td style="padding:0 0 16px">
    <table role="presentation" cellpadding="0" cellspacing="0" border="0"><tr>
      <td valign="middle" style="padding-right:11px">{_logo()}</td>
      <td valign="middle">
        <div style="font-family:{DISPLAY};font-size:17px;font-weight:600;color:{INK};
          line-height:1.2">The Grid</div>
      </td>
    </tr></table>
  </td></tr>

  <tr><td style="padding:0 0 4px;font-family:{DISPLAY};font-size:10.5px;font-weight:600;
    letter-spacing:.16em;text-transform:uppercase;color:{BRAND}">Connections</td></tr>
  <tr><td style="font-family:{DISPLAY};font-size:24px;font-weight:700;
    color:{INK};line-height:1.25;padding:0 0 8px">{escape(title)}</td></tr>
  <tr><td style="font-size:13px;line-height:1.55;color:{INK2};padding:0 0 18px">{intro}</td></tr>

  <tr><td>{body}</td></tr>

  <tr><td style="padding:20px 0 0">
    <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%"
      style="border-collapse:collapse;background:{PANEL};border:1px solid {LINE};border-radius:12px">
      <tr><td style="padding:17px 18px 18px;font-size:12.5px;color:{INK2};line-height:1.6">
        <table role="presentation" cellpadding="0" cellspacing="0" border="0"
          style="border-collapse:separate"><tr>
          <td align="center" bgcolor="{BRAND}" style="border-radius:4px">
            <a href="{escape(grid_url)}" style="display:inline-block;padding:13px 20px;
              font-family:{DISPLAY};font-size:11.5px;font-weight:600;letter-spacing:2px;
              text-transform:uppercase;color:#FFFFFF;text-decoration:none">Open The Connections Tab</a>
          </td>
        </tr></table>
        <div style="color:{INK3};font-size:11.5px;padding-top:13px">One email per state change,
        plus one morning digest while anything is still red. Reply-all to hand the fix to someone.</div>
      </td></tr>
    </table>
  </td></tr>

  <tr><td style="padding:16px 2px 0;border-top:1px solid {LINE};margin-top:16px">
    <div style="font-size:10.5px;color:{INK3};padding-top:14px">
      windsor-connections-probe &middot; hourly &middot; bidbrain-analytics
    </div>
  </td></tr>

</table></td></tr></table></body></html>"""


def _row(label: str, value: str) -> str:
    return (f'<tr>'
            f'<td style="padding:7px 14px 7px 0;font-size:9.5px;font-weight:700;letter-spacing:.07em;'
            f'text-transform:uppercase;color:{INK3};white-space:nowrap;vertical-align:top;'
            f'border-top:1px solid {LINE2}">{escape(label)}</td>'
            f'<td style="padding:7px 0;font-size:12.5px;color:{INK};line-height:1.5;'
            f'vertical-align:top;border-top:1px solid {LINE2}">{value}</td></tr>')


def _card(inner: str, accent: str) -> str:
    """A panel with the state colour as a rule along the BOTTOM edge.

    Two rows rather than a styled border: Outlook drops a border on one side often enough that a
    filled cell is the only version that renders everywhere. The bar needs font-size and
    line-height zeroed as well as a height, or the non-breaking space inside props it open to a
    full text line."""
    return (f'<table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" '
            f'style="border-collapse:collapse;margin:0 0 12px">'
            f'<tr><td style="background:{PANEL};border:1px solid {LINE};border-bottom:0;'
            f'border-radius:6px 6px 0 0;padding:15px 18px">{inner}</td></tr>'
            f'<tr><td height="3" style="height:3px;line-height:3px;font-size:0;'
            f'background:{accent};border-radius:0 0 6px 6px">&nbsp;</td></tr>'
            f'</table>')


def _head(client: str, feed: str, account: str = "", acct_id: str = "") -> str:
    """Card heading. Was display:flex, which Outlook ignores, so the client name and the
    feed collapsed onto each other there. Plain inline spans work everywhere."""
    h = (f'<div style="font-family:{DISPLAY};font-size:14.5px;font-weight:600;color:{INK};'
         f'line-height:1.35">{escape(client or "Unmapped")}'
         f'<span style="color:{INK3};font-weight:500;font-size:12.5px"> &middot; {escape(feed)}</span></div>')
    if account:
        h += (f'<div style="font-size:12px;color:{INK2};padding:3px 0 10px">{escape(account)}'
              + (f' <span style="font-family:Consolas,Menlo,monospace;font-size:11px;color:{INK3}">'
                 f'{escape(acct_id)}</span>' if acct_id else '') + '</div>')
    return h


def render_change_email(changes: list[dict], red: list, doc: dict, grid_url: str) -> dict:
    worsened = [c for c in changes if c["new"] in ("not_granted", "frozen", "error")]
    recovered = [c for c in changes if c["new"] not in ("not_granted", "frozen", "error")]
    if worsened and not recovered:
        head = f"{len(worsened)} Windsor account{'s' if len(worsened) != 1 else ''} need{'s' if len(worsened) == 1 else ''} attention"
    elif recovered and not worsened:
        head = f"{len(recovered)} Windsor account{'s' if len(recovered) != 1 else ''} recovered"
    else:
        head = f"Windsor: {len(worsened)} down, {len(recovered)} recovered"
    subj = f"[Windsor] {head}: " + ", ".join(sorted({c['client'] for c in changes if c.get('client')}))[:90]

    cards = []
    for c in worsened + recovered:
        inner = (_head(c["client"], c["ds"], c["account"], c["id"])
                 + '<table role="presentation" cellspacing="0" cellpadding="0" border="0" width="100%" style="border-collapse:collapse">'
                 + _row("State", f"{_pill(c['old'])} &nbsp;→&nbsp; {_pill(c['new'])}")
                 + _row("Means", escape(STATE_MEANING.get(c["new"], "")))
                 + (_row("Newest data", escape(c["newest_day"])) if c.get("newest_day") else "")
                 + (_row("Do this", escape(c["fix"])) if c.get("fix") and c["new"] in ("not_granted", "frozen", "error") else "")
                 + "</table>")
        cards.append(_card(inner, STATE_COLOR.get(c["new"], INK3)))

    still = [(d, a) for d, a in red if not any(c["id"] == a["id"] and c["ds"] == d["label"] for c in changes)]
    tail = ""
    if still:
        tail = (f'<div style="font-family:{DISPLAY};font-size:10.5px;font-weight:700;'
                f'letter-spacing:.1em;text-transform:uppercase;color:{INK3};padding:20px 0 8px">'
                f'Still red from earlier</div>'
                + "".join(f'<div style="font-size:12.5px;color:{INK2};padding:8px 0;'
                          f'border-top:1px solid {LINE}">{_pill(a["state"])} &nbsp;'
                          f'<b style="color:{INK}">{escape(a["client_label"] or "Unmapped")}</b> &middot; '
                          f'{escape(d["label"])} &middot; {escape(a["name"] or a["id"])} '
                          f'<span style="color:{INK3}">since {escape(a["since"])}</span></div>'
                          for d, a in still))

    intro = ("The hourly probe of every Windsor account we ingest saw a state change. A grant that lapses never fails a job - "
             "the dashboard just keeps yesterday's numbers - so this email is the alarm.")
    html = _shell(head, intro, "".join(cards) + tail, grid_url)
    text = head + "\n\n" + "\n".join(f"- {c['client']} / {c['ds']} / {c['account']}: {c['old']} -> {c['new']}. {c.get('fix') or ''}" for c in changes) + f"\n\n{grid_url}"
    return {"subject": subj, "html": html, "text": text}


def render_digest_email(red: list, doc: dict, grid_url: str) -> dict:
    n = len(red)
    subj = f"[Windsor] Morning digest: {n} account{'s' if n != 1 else ''} still need{'s' if n == 1 else ''} attention"
    rows = "".join(
        _card(_head(a["client_label"], d["label"], a["name"] or a["id"])
              + '<table role="presentation" cellspacing="0" cellpadding="0" border="0" width="100%" style="border-collapse:collapse">'
              + _row("State", f"{_pill(a['state'])} &nbsp;<span style='color:#879089'>since {escape(a['since'])} ({a['since_days']} d)</span>")
              + (_row("Newest data", escape(a["data"].get("newest_day") or "-") + (f" &nbsp;<span style='color:#879089'>{a['data']['days_behind']} d behind</span>" if a["data"].get("days_behind") is not None else "")))
              + _row("Do this", escape(a["fix"] or ""))
              + "</table>", STATE_COLOR.get(a["state"], INK3))
        for d, a in sorted(red, key=lambda x: (x[1]["state"] != "not_granted", x[1]["client_label"] or ""))
    )
    intro = "Nothing new since the last alert - this is the once-a-day reminder that these are still open. It stops the morning after the last one clears."
    html = _shell(f"{n} Windsor account{'s' if n != 1 else ''} still red", intro, rows, grid_url)
    text = subj + "\n\n" + "\n".join(f"- {a['client_label']} / {d['label']} / {a['name'] or a['id']}: {a['state']} since {a['since']}. {a['fix'] or ''}" for d, a in red) + f"\n\n{grid_url}"
    return {"subject": subj, "html": html, "text": text}


def render_expiry_email(d: dict, days: int, grid_url: str) -> dict:
    g = d.get("grant") or {}
    when = "is past its estimated expiry" if days < 0 else f"is likely to expire in about {days} day{'s' if days != 1 else ''}"
    subj = f"[Windsor] {d['label']} grant {when} (estimate)"
    clients = sorted({a["client_label"] for a in d["accounts"] if a.get("client") and a.get("alerts")})
    inner = (f'<div style="font-family:{DISPLAY};font-size:14.5px;font-weight:600;color:{INK}">'
             f'{escape(d["label"])}</div>'
             + '<table role="presentation" cellspacing="0" cellpadding="0" border="0" width="100%" style="border-collapse:collapse;margin-top:6px">'
             + _row("Last re-authorised", escape(g.get("last_reauth") or "-") + (f" by {escape(g['reauth_by'])}" if g.get("reauth_by") else ""))
             + _row("Typical lifetime", f"{g.get('token_lifetime_days')} days")
             + _row("Estimated expiry", escape(g.get("expiry_estimate") or "-"))
             + _row("Dashboards on it", escape(", ".join(clients)) if clients else "none on a critical path")
             + _row("Do this", f"Ask the connector owner to re-grant before then at <a href='{escape(d['reauth_url'])}'>onboard.windsor.ai</a>. The next hourly probe sees the re-grant and resets this countdown by itself.")
             + "</table>")
    intro = ("Windsor publishes no token expiry, so this is our own countdown: the date this connector was last re-authorised plus "
             "the platform's typical token lifetime. Treat it as a heads-up, not a certainty - re-granting early costs nothing, a lapse costs a week of wrong numbers.")
    html = _shell(f"{d['label']} grant {when}", intro, _card(inner, STATE_COLOR["frozen"]), grid_url)
    text = subj + f"\n\nLast re-auth {g.get('last_reauth')}, lifetime {g.get('token_lifetime_days')} d, estimate {g.get('expiry_estimate')}. Re-grant: {d['reauth_url']}\n{grid_url}"
    return {"subject": subj, "html": html, "text": text}


def send_gmail(token_json: str, to: list[str], subject: str, html: str, text: str) -> tuple[bool, str | None]:
    """Send one message as the token's owner. Returns (sent, error)."""
    try:
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
        from googleapiclient.discovery import build

        info = json.loads(token_json)
        creds = Credentials.from_authorized_user_info(info, scopes=["https://www.googleapis.com/auth/gmail.send"])
        if not creds.valid:
            if creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                return False, "Gmail token invalid and not refreshable - regenerate with gen_gmail_token.py"
        svc = build("gmail", "v1", credentials=creds, cache_discovery=False)
        msg = EmailMessage()
        msg["To"] = ", ".join(to)
        msg["Subject"] = subject
        # Declare this as machine-generated (RFC 3834). Without it the message looks like a
        # person hand-sending templated HTML to another domain, which is close to the shape of
        # bulk mail - the first test send landed in spam. This does not on its own guarantee
        # inbox placement (see README: each recipient still needs one "never send to spam"
        # filter), but it is the correct declaration and it stops the other half of the
        # problem: an out-of-office auto-reply bouncing back at an alert address.
        msg["Auto-Submitted"] = "auto-generated"
        msg["X-Auto-Response-Suppress"] = "All"
        msg.set_content(text)
        msg.add_alternative(html, subtype="html")
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        svc.users().messages().send(userId="me", body={"raw": raw}).execute()
        return True, None
    except Exception as e:  # noqa: BLE001
        return False, f"{type(e).__name__}: {str(e)[:200]}"
