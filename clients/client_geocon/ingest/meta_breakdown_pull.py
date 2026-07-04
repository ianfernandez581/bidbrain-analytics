"""
Geocon-ONLY Meta breakdown pull — audience (age/gender), placement, region.

ISOLATION (by design — this cannot affect any other client):
  * Separate script; does NOT import or touch the shared windsor_data_pull/meta/meta_loader.py.
  * Writes NDJSON destined for a NEW geocon-only table `raw_windsor.geocon_meta_breakdown`
    (loaded via `bq load --replace` in the deploy step). It does NOT write perf_meta.
  * Read-only Windsor calls, scoped to Geocon's account (3754165911553001) and filtered to
    `Geocon_` campaigns before anything is written.

The standard perf_meta table can't carry these because Windsor breakdowns multiply the row grain
(age x gender x placement x region), and perf_meta is a SHARED table feeding every Meta client.

RUN (key comes from Secret Manager via the gcloud CLI, so no ADC needed):
    WINDSOR_API_KEY="$(gcloud secrets versions access latest --secret=windsor-api-key | tr -d '\r\n')" \
      python clients/client_geocon/ingest/meta_breakdown_pull.py 2026-05-01 2026-07-04 out.ndjson
then:
    bq load --replace --source_format=NEWLINE_DELIMITED_JSON \
      raw_windsor.geocon_meta_breakdown out.ndjson \
      date:DATE,campaign:STRING,breakdown:STRING,seg1:STRING,seg2:STRING,impressions:INTEGER,reach:INTEGER,clicks:INTEGER,link_clicks:INTEGER,spend:FLOAT,leads:INTEGER
"""
import os, sys, json, requests

ACCOUNT = "facebook__3754165911553001"          # Geocon's Meta account ("100% Digital - Clients")
URL = "https://connectors.windsor.ai/all"
BASE = "date,campaign,impressions,spend,clicks,link_clicks,reach,actions_lead"
# Windsor breakdown field ids (from raw_windsor.windsor_fields): age, gender, platform_position (=Ad Placement), region
PULLS = [("age_gender", ["age", "gender"]), ("placement", ["platform_position"]), ("region", ["region"])]

def ni(v):
    if v in (None, "", "null"): return None
    try: return int(float(v))
    except (TypeError, ValueError): return None

def nf(v):
    if v in (None, "", "null"): return None
    try: return float(v)
    except (TypeError, ValueError): return None

def pull(key, d_from, d_to, dims):
    fields = ",".join(dims) + "," + BASE
    r = requests.get(URL, params={"api_key": key, "date_from": d_from, "date_to": d_to,
                                  "fields": fields, "select_accounts": ACCOUNT}, timeout=180)
    r.raise_for_status()
    return r.json().get("data", [])

def main():
    key = os.environ["WINDSOR_API_KEY"]
    d_from, d_to, out = sys.argv[1], sys.argv[2], sys.argv[3]
    total = 0
    with open(out, "w", encoding="utf-8") as f:
        for bk, dims in PULLS:
            rows = pull(key, d_from, d_to, dims)
            kept = 0
            for x in rows:
                if not str(x.get("campaign", "")).startswith("Geocon_"):
                    continue
                f.write(json.dumps({
                    "date": x.get("date"), "campaign": x.get("campaign"), "breakdown": bk,
                    "seg1": x.get(dims[0]), "seg2": (x.get(dims[1]) if len(dims) > 1 else None),
                    "impressions": ni(x.get("impressions")), "reach": ni(x.get("reach")),
                    "clicks": ni(x.get("clicks")), "link_clicks": ni(x.get("link_clicks")),
                    "spend": nf(x.get("spend")), "leads": ni(x.get("actions_lead")),
                }) + "\n")
                kept += 1
            print(f"  {bk}: {len(rows)} rows fetched, {kept} Geocon rows written")
            total += kept
    print(f"wrote {total} rows -> {out}")

if __name__ == "__main__":
    main()
