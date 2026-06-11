FROM python:3.12.13-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY main.py freshness.py ./
# Drop root: least privilege (the job reads Snowflake metadata + counts, BigQuery
# __TABLES__ metadata, and each client bucket's JSON; it writes only status.json).
RUN useradd -m -u 10001 appuser && chown -R appuser /app
USER appuser
CMD ["python", "main.py"]
