# windsor-connections-probe - Cloud Run job image.
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY probe.py mailer.py config.json ./
RUN useradd -u 10001 -m appuser
USER appuser
CMD ["python", "probe.py"]
