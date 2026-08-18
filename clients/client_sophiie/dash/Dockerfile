FROM python:3.12.13-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY main.py report.py platform_sso.py dashboard.html placeholder.json bb_deck.js logo.png ./
# The marble texture the Chronicle skin paints onto the masthead, KPI slab and panels. Served as
# FILES, not base64: 352KB of JPEG inlined would add ~470KB to dashboard.html. CSS references them
# RELATIVELY (url("marble-cell.jpg")), which resolves both direct and behind the platform proxy.
COPY marble-band.jpg marble-cell.jpg marble-tile.jpg ./
# Drop root: Cloud Run does not need it (least privilege).
RUN useradd -m -u 10001 appuser && chown -R appuser /app
USER appuser
ENV PORT=8080
# --timeout 0 is intentional: Cloud Run enforces the request timeout itself.
CMD exec gunicorn --bind :$PORT --workers 2 --threads 8 --timeout 0 main:app
