r"""
One-time, LOCAL: generate the Gmail OAuth token for the intake job.

Prereqs (in the GCP console, project bidbrain-analytics)
--------------------------------------------------------
1. Enable the Gmail API.
2. APIs & Services -> OAuth consent screen: set it up (External), and add
   schneiderreports01@gmail.com as a Test user (or publish the app - see the
   note about the 7-day refresh-token expiry in the README).
3. APIs & Services -> Credentials -> Create credentials -> OAuth client ID ->
   Application type "Desktop app". Download the JSON as `client_secret.json`
   into this folder. (gcloud cannot create OAuth *client* creds - console only.)

Run
---
   ..\..\.venv\Scripts\python.exe gen_gmail_token.py

A browser opens; log in AS schneiderreports01@gmail.com and approve. It writes
`token.json` here. Then upload it to Secret Manager and DELETE the local copy:

   gcloud secrets create schneider-gmail-oauth --project bidbrain-analytics --data-file=token.json
   # (or a new version if it already exists:)
   gcloud secrets versions add schneider-gmail-oauth --project bidbrain-analytics --data-file=token.json
   del token.json client_secret.json

Never commit token.json or client_secret.json (the local .gitignore blocks them).
"""

from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]


def main():
    flow = InstalledAppFlow.from_client_secrets_file("client_secret.json", SCOPES)
    creds = flow.run_local_server(port=0)
    with open("token.json", "w", encoding="utf-8") as f:
        f.write(creds.to_json())
    print(
        "Wrote token.json. Next: upload it to Secret Manager as "
        "'schneider-gmail-oauth', then delete token.json + client_secret.json."
    )


if __name__ == "__main__":
    main()
