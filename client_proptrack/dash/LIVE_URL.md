# PropTrack dashboard — live URL

**Not deployed yet.** Run the first-time stand-up to provision and deploy:

```powershell
.\client_proptrack\deploy_proptrack.ps1
```

It prints the live `…run.app` URL at the end (and prompts you to choose the dashboard password, stored in
Secret Manager as `proptrack-dash-password`). Once deployed, record the URL here.

Password-gated: the page loads a login screen; enter the dashboard password to view it.
- Read the current password: `gcloud secrets versions access latest --secret=proptrack-dash-password`.
- Rotate it: `printf '%s' 'NEW' | gcloud secrets versions add proptrack-dash-password --data-file=-` (no redeploy — the service reads `:latest`).

The `…run.app` URL is harmless without the password: it only shows the login screen. The data file
(`proptrack.json`) lives in a **private** bucket and is served only to an authenticated session via
`/data.json` — never publicly.

## Custom domain (optional, not yet wired)

To put it on `proptrack.bidbrain.ai`: add a CNAME in Cloudflare DNS → the `…run.app` host above, Proxied,
SSL Full (strict), with a **Host Header Override** to the run.app host (mirrors the other clients).
