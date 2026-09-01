FROM python:3.12.13-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# Both GA4 loaders ship in one job: acquisition (perf_ga4) then events (perf_ga4_events).
# The job is pinned to a property subset via the GA4_ACCOUNTS env var set at deploy time
# (see scripts/deploy_ingest_jobs.ps1) - without it a scheduled run would attempt full
# backfills for every property in the loaders' laptop lists.
COPY ga4_loader.py events_loader.py ./
# Drop root: least privilege (the job only talks to Windsor API / Secret Manager / BigQuery / GCS).
RUN useradd -m -u 10001 appuser && chown -R appuser /app
USER appuser
CMD ["sh", "-c", "python ga4_loader.py && python events_loader.py"]
