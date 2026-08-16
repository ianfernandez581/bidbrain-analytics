FROM python:3.12.13-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY main.py store.py config.py platform_sso.py feedback.py feedback_ai.py logo.svg ./
COPY internal_notes.py internal_chat.py feedback_loop_data.py ./
COPY lineage ./lineage
# Agency logos: copied by WILDCARD, because main.py discovers them by globbing `agency_*` /
# `admlogo_*` at startup. Naming each file here meant a new agency's logo was committed but never
# reached the image, so its portal silently fell back to a plain text heading - exactly what
# happened to Extrablack. Adding an agency logo is now just dropping the file in this folder.
COPY agency_* ./
COPY admlogo_* ./
COPY favicon.ico favicon-32.png apple-touch-icon.png ./
COPY templates ./templates
# Drop root: Cloud Run does not need it (least privilege).
RUN useradd -m -u 10001 appuser && chown -R appuser /app
USER appuser
ENV PORT=8080
# --timeout 0 is intentional: Cloud Run enforces the request timeout itself.
CMD exec gunicorn --bind :$PORT --workers 2 --threads 8 --timeout 0 main:app
