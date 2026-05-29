# bidbrain-analytics

Data pipelines for Bidbrain client reporting (Google Cloud + BigQuery).
Project: bidbrain-analytics  |  Region: australia-southeast1 (Sydney)

## Layout
- mongodb-job/   - Cloud Run job: Snowflake -> BigQuery -> builds mongodb.json in GCS
- cloudflare/    - Cloudflare client reporting pipeline
- loader.py      - Windsor.ai -> BigQuery loader (raw_windsor)
- create_dataset.py / create_tables.py - one-time BigQuery setup

## BigQuery datasets
- raw_windsor        - shared raw Windsor.ai data
- client_mongodb     - MongoDB client tables + views
- client_cloudflare  - Cloudflare client data

## Secrets
Credentials + cached data live OUTSIDE this repo (local bidbrain-vault/, and GCP Secret Manager).
Nothing sensitive belongs in git.
