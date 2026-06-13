FROM python:3.12.13-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY loader.py freshness.py ./
# Drop root: least privilege (the job only talks to Snowflake / Secret Manager / BigQuery).
RUN useradd -m -u 10001 appuser && chown -R appuser /app
USER appuser
CMD ["python", "loader.py"]
