FROM python:3.12.13-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# No logo.svg / icon.png: no Ray White Projects artwork has been supplied, so the lockup on both
# the login and the dashboard is a typographic stand-in in markup and the favicon is an inline
# data URI. gen_brand_assets.py adds the real files, and this COPY line, in one change.
COPY main.py platform_sso.py dashboard.html placeholder.json internal_notes.json ./
# Drop root: Cloud Run does not need it (least privilege).
RUN useradd -m -u 10001 appuser && chown -R appuser /app
USER appuser
ENV PORT=8080
# --timeout 0 is intentional: Cloud Run enforces the request timeout itself.
CMD exec gunicorn --bind :$PORT --workers 2 --threads 8 --timeout 0 main:app
