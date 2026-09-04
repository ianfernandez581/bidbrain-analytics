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


def _pill(state: str) -> str:
    return (f'<span style="display:inline-block;padding:2px 9px;border-radius:999px;font-size:11px;font-weight:700;'
            f'color:#fff;background:{STATE_COLOR.get(state, "#6F827A")}">{escape(STATE_LABEL.get(state, state))}</span>')


def _shell(title: str, intro: str, body: str, grid_url: str) -> str:
    return f"""<!doctype html><html><body style="margin:0;padding:0;background:#F4F7F5;font-family:Inter,Segoe UI,Arial,sans-serif;color:#0F1A14">
<div style="max-width:680px;margin:0 auto;padding:28px 18px">
  <div style="font-size:11px;font-weight:700;letter-spacing:.16em;text-transform:uppercase;color:#1FB573">The Grid · Connections</div>
  <h1 style="font-size:20px;margin:6px 0 6px;letter-spacing:-.3px">{escape(title)}</h1>
  <p style="margin:0 0 18px;font-size:13.5px;line-height:1.55;color:#566159">{intro}</p>
  {body}
  <p style="margin:22px 0 0;font-size:12px;color:#566159">Full per-account view: <a href="{escape(grid_url)}" style="color:#0A7647;font-weight:600">open the Connections tab</a>.
  This is one email per state change, plus one morning digest while anything is still red. Reply-all to hand the fix to someone.</p>
  <p style="margin:14px 0 0;font-size:11px;color:#879089">windsor-connections-probe · hourly · bidbrain-analytics</p>
</div></body></html>"""


def _row(label: str, value: str) -> str:
    return (f'<tr><td style="padding:6px 10px 6px 0;font-size:12px;color:#566159;white-space:nowrap;vertical-align:top">{escape(label)}</td>'
            f'<td style="padding:6px 0;font-size:12.5px;vertical-align:top">{value}</td></tr>')


def _card(inner: str, accent: str) -> str:
    return (f'<div style="background:#fff;border:1px solid #E4EAE6;border-left:4px solid {accent};border-radius:12px;'
            f'padding:14px 16px;margin:0 0 12px">{inner}</div>')


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
        inner = (f'<div style="display:flex;align-items:center;gap:8px;font-size:14px;font-weight:700">{escape(c["client"] or "Unmapped")}'
                 f' <span style="color:#879089;font-weight:500">· {escape(c["ds"])}</span></div>'
                 f'<div style="font-size:12px;color:#566159;margin:2px 0 10px">{escape(c["account"])} <code style="font-size:11px;color:#879089">{escape(c["id"])}</code></div>'
                 f'<table cellspacing="0" cellpadding="0" style="border-collapse:collapse">'
                 + _row("State", f"{_pill(c['old'])} &nbsp;→&nbsp; {_pill(c['new'])}")
                 + _row("Means", escape(STATE_MEANING.get(c["new"], "")))
                 + (_row("Newest data", escape(c["newest_day"])) if c.get("newest_day") else "")
                 + (_row("Do this", escape(c["fix"])) if c.get("fix") and c["new"] in ("not_granted", "frozen", "error") else "")
                 + "</table>")
        cards.append(_card(inner, STATE_COLOR.get(c["new"], "#6F827A")))

    still = [(d, a) for d, a in red if not any(c["id"] == a["id"] and c["ds"] == d["label"] for c in changes)]
    tail = ""
    if still:
        tail = ('<h3 style="font-size:13px;margin:18px 0 8px;color:#566159;text-transform:uppercase;letter-spacing:.05em">Still red from earlier</h3>'
                + "".join(f'<div style="font-size:12.5px;padding:5px 0;border-top:1px solid #E4EAE6">{_pill(a["state"])} &nbsp;<b>{escape(a["client_label"] or "Unmapped")}</b> · {escape(d["label"])} · {escape(a["name"] or a["id"])} <span style="color:#879089">since {escape(a["since"])}</span></div>' for d, a in still))

    intro = ("The hourly probe of every Windsor account we ingest saw a state change. A grant that lapses never fails a job - "
             "the dashboard just keeps yesterday's numbers - so this email is the alarm.")
    html = _shell(head, intro, "".join(cards) + tail, grid_url)
    text = head + "\n\n" + "\n".join(f"- {c['client']} / {c['ds']} / {c['account']}: {c['old']} -> {c['new']}. {c.get('fix') or ''}" for c in changes) + f"\n\n{grid_url}"
    return {"subject": subj, "html": html, "text": text}


def render_digest_email(red: list, doc: dict, grid_url: str) -> dict:
    n = len(red)
    subj = f"[Windsor] Morning digest: {n} account{'s' if n != 1 else ''} still need{'s' if n == 1 else ''} attention"
    rows = "".join(
        _card(f'<div style="font-size:14px;font-weight:700">{escape(a["client_label"] or "Unmapped")} <span style="color:#879089;font-weight:500">· {escape(d["label"])}</span></div>'
              f'<div style="font-size:12px;color:#566159;margin:2px 0 8px">{escape(a["name"] or a["id"])}</div>'
              f'<table cellspacing="0" cellpadding="0" style="border-collapse:collapse">'
              + _row("State", f"{_pill(a['state'])} &nbsp;<span style='color:#879089'>since {escape(a['since'])} ({a['since_days']} d)</span>")
              + (_row("Newest data", escape(a["data"].get("newest_day") or "-") + (f" &nbsp;<span style='color:#879089'>{a['data']['days_behind']} d behind</span>" if a["data"].get("days_behind") is not None else "")))
              + _row("Do this", escape(a["fix"] or ""))
              + "</table>", STATE_COLOR.get(a["state"], "#6F827A"))
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
    inner = (f'<div style="font-size:14px;font-weight:700">{escape(d["label"])}</div>'
             f'<table cellspacing="0" cellpadding="0" style="border-collapse:collapse;margin-top:8px">'
             + _row("Last re-authorised", escape(g.get("last_reauth") or "-") + (f" by {escape(g['reauth_by'])}" if g.get("reauth_by") else ""))
             + _row("Typical lifetime", f"{g.get('token_lifetime_days')} days")
             + _row("Estimated expiry", escape(g.get("expiry_estimate") or "-"))
             + _row("Dashboards on it", escape(", ".join(clients)) if clients else "none on a critical path")
             + _row("Do this", f"Ask the connector owner to re-grant before then at <a href='{escape(d['reauth_url'])}'>onboard.windsor.ai</a>. The next hourly probe sees the re-grant and resets this countdown by itself.")
             + "</table>")
    intro = ("Windsor publishes no token expiry, so this is our own countdown: the date this connector was last re-authorised plus "
             "the platform's typical token lifetime. Treat it as a heads-up, not a certainty - re-granting early costs nothing, a lapse costs a week of wrong numbers.")
    html = _shell(f"{d['label']} grant {when}", intro, _card(inner, "#B45309"), grid_url)
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
        msg.set_content(text)
        msg.add_alternative(html, subtype="html")
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        svc.users().messages().send(userId="me", body={"raw": raw}).execute()
        return True, None
    except Exception as e:  # noqa: BLE001
        return False, f"{type(e).__name__}: {str(e)[:200]}"
