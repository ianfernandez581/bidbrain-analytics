"""One-time, LOCAL: mint the Gmail SEND token the connections probe alerts with.

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
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/gmail.send"]

if __name__ == "__main__":
    flow = InstalledAppFlow.from_client_secrets_file("client_secret.json", SCOPES)
    creds = flow.run_local_server(port=0, prompt="consent", access_type="offline")
    with open("token.json", "w", encoding="utf-8") as f:
        f.write(creds.to_json())
    print("Wrote token.json (scope: gmail.send). Next: upload it to Secret Manager as "
          "'windsor-alerts-gmail-oauth', then delete token.json + client_secret.json.")
