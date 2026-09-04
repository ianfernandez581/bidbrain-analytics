r"""One-time, LOCAL: mint the Gmail SEND token the connections probe alerts with.

Run this as the mailbox the alerts should come FROM (ian@100.digital, or a shared
alerts@ mailbox). Steps:

1. Google Cloud console -> APIs & Services -> Credentials (project bidbrain-analytics):
   OAuth client ID, application type "Desktop app". Download the JSON as client_secret.json
   into this folder. Enable the Gmail API on the project if it is not already.
   IMPORTANT: on the OAuth consent screen set User type = INTERNAL (a 100.digital Workspace
   app). An EXTERNAL app left in "Testing" issues refresh tokens that die after 7 days, which
   would make the expiry monitor the first thing to expire.
2. From the repo root:
       .\.venv\Scripts\python.exe ingest\windsor_data_pull\connections\gen_gmail_token.py
   A browser opens; sign in as the sending mailbox and grant "Send email on your behalf".
   It writes token.json here (scope gmail.send ONLY - it cannot read the mailbox).
3. Upload it to Secret Manager and DELETE the local copies:
       gcloud secrets create windsor-alerts-gmail-oauth --project bidbrain-analytics --data-file=token.json
     (or, to rotate)
       gcloud secrets versions add windsor-alerts-gmail-oauth --project bidbrain-analytics --data-file=token.json
       del token.json client_secret.json
4. Redeploy is NOT needed - the job reads the latest secret version on every run.

Never commit token.json or client_secret.json (gitignored here).
"""
import sys
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/gmail.send"]

# Anchor both files to THIS folder, never the working directory. Run from the repo root
# (which is how every other script here is invoked) and a bare relative path would miss
# client_secret.json AND write token.json to the repo root - outside the .gitignore beside
# this file that is the only thing stopping a live credential being committed.
HERE = Path(__file__).resolve().parent
CLIENT_SECRET = HERE / "client_secret.json"
TOKEN = HERE / "token.json"

if __name__ == "__main__":
    if not CLIENT_SECRET.exists():
        sys.exit(f"ERROR: {CLIENT_SECRET} not found.\n"
                 "Create an OAuth client ID (type: Desktop app) at\n"
                 "  https://console.cloud.google.com/apis/credentials?project=bidbrain-analytics\n"
                 f"and save its JSON as:\n  {CLIENT_SECRET}\n"
                 "See this file's header for the full runbook.")
    flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_SECRET), SCOPES)
    creds = flow.run_local_server(port=0, prompt="consent", access_type="offline")
    TOKEN.write_text(creds.to_json(), encoding="utf-8")
    print(f"\nWrote {TOKEN}\n"
          "  scope: gmail.send only - this token CANNOT read the mailbox.\n\n"
          "Next, upload it and delete BOTH local files (they are live credentials):\n"
          f'  gcloud secrets create windsor-alerts-gmail-oauth --project bidbrain-analytics --data-file="{TOKEN}"\n'
          f'  del "{TOKEN}" "{CLIENT_SECRET}"\n')
