"""Verify the TLM views were applied correctly."""
from google.cloud import bigquery

bq = bigquery.Client(project="bidbrain-analytics", location="australia-southeast1")
views = ["kpi", "monthly", "weekly", "google_campaigns", "google_by_type",
         "ttd_campaigns", "ttd_creative", "ad_campaigns", "ad_campaign_monthly",
         "ad_campaign_weekly", "stg_google", "stg_ttd", "stg_ad_delivery"]
ok = True
for v in views:
    try:
        r = next(bq.query(f"SELECT COUNT(*) AS n FROM `bidbrain-analytics.client_tlm.{v}`").result())
        print(f"  {v}: {r['n']} row(s)")
    except Exception as e:
        print(f"  {v}: ERROR — {e}")
        ok = False
print("\nAll views verified." if ok else "\nSOME VIEWS FAILED — check errors above.")