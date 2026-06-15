FROM python:3.12.13-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY main.py platform_sso.py report.py dashboard.html ./
# Drop root: Cloud Run does not need it (least privilege).
RUN useradd -m -u 10001 appuser && chown -R appuser /app
USER appuser
ENV PORT=8080
# --timeout 0 is intentional: Cloud Run enforces the request timeout itself.
CMD exec gunicorn --bind :$PORT --workers 2 --threads 8 --timeout 0 main:app
