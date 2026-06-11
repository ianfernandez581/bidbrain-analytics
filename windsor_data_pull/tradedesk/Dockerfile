FROM python:3.12.13-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY tradedesk_loader.py .
# Drop root: least privilege (the job only talks to Windsor API / Secret Manager / BigQuery / GCS).
RUN useradd -m -u 10001 appuser && chown -R appuser /app
USER appuser
CMD ["python", "tradedesk_loader.py"]
