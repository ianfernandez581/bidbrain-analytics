"""Grant a service account dataset-level WRITER (= roles/bigquery.dataEditor) on ONE BigQuery dataset.

Used by deploy_job_status_deploy.ps1 so status-deploy@ can WRITE_TRUNCATE the client_<c>.seed_* tables
WITHOUT project-wide dataEditor (which would let the "Make this live" worker overwrite the raw_* mirrors
and every client's tables — far too broad for a SA a web button triggers). Scoped, idempotent.

Run: python grant_dataset_writer.py <dataset> <sa-email>
"""
import sys
from google.cloud import bigquery

PROJECT = "bidbrain-analytics"


def main():
    if len(sys.argv) != 3:
        raise SystemExit("usage: grant_dataset_writer.py <dataset> <sa-email>")
    dataset, member = sys.argv[1], sys.argv[2]
    c = bigquery.Client(project=PROJECT)
    ds = c.get_dataset(f"{PROJECT}.{dataset}")
    entries = list(ds.access_entries)
    if any(e.entity_id == member and e.role == "WRITER" for e in entries):
        print(f"{member} already WRITER on {dataset}")
        return
    entries.append(bigquery.AccessEntry("WRITER", "userByEmail", member))
    ds.access_entries = entries
    c.update_dataset(ds, ["access_entries"])
    print(f"granted WRITER on {dataset} to {member}")


if __name__ == "__main__":
    main()
