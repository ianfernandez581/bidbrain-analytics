FROM python:3.12.13-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY main.py store.py config.py platform_sso.py feedback.py feedback_ai.py logo.svg ./
COPY internal_notes.py internal_chat.py feedback_loop_data.py ./
# The knowledge base. 🔴 THE INDEX IS PER PROCESS and this runs two gunicorn workers, so the
# service holds TWO copies of the corpus plus numpy per worker. It needs more than the original
# 512Mi; `deploy_dash_platform.ps1` is an image swap and will not set that, so memory is a one-time
# `gcloud run services update platform-dash --memory 1Gi`.
COPY kb_store.py kb_chunk.py kb_embed.py kb_index.py kb_extract.py kb_routes.py ./
COPY kb_chat.py kb_prompt.py kb_feedback.py kb_activity.py kb_trace.py ./
# 🔴 The self-knowledge document is SHIPPED, not summarised: kb_prompt reads it and puts it in the
# prompt on every turn, so a rule change is a text edit here rather than a code change.
COPY kb ./kb
# The Documents explorer, the Ask panel and the Observability page. Flask serves this folder at
# /static; before the knowledge base there was no static folder at all.
COPY static ./static
COPY lineage ./lineage
# Agency logos: copied by WILDCARD, because main.py discovers them by globbing `agency_*` /
# `admlogo_*` at startup. Naming each file here meant a new agency's logo was committed but never
# reached the image, so its portal silently fell back to a plain text heading - exactly what
# happened to Extrablack. Adding an agency logo is now just dropping the file in this folder.
COPY agency_* ./
COPY admlogo_* ./
# Per-CLIENT marks for the themed portals' tiles, discovered the same way (main._load_client_logos
# globs `clientlogo_*`). They were committed on 2026-08-15 but never listed here, so CLIENT_LOGOS
# was empty in the image and every themed tile silently fell back to its plain text heading - the
# identical failure the comment above describes, one glob down. Found in QA on 2026-08-26.
COPY clientlogo_* ./
COPY favicon.ico favicon-32.png apple-touch-icon.png ./
COPY templates ./templates
# "How The Brain works" explainer pages, served by /brain/how-it-works/<slug> (100% Digital portal).
COPY explainers ./explainers
# Drop root: Cloud Run does not need it (least privilege).
RUN useradd -m -u 10001 appuser && chown -R appuser /app
USER appuser
ENV PORT=8080
# --timeout 0 is intentional: Cloud Run enforces the request timeout itself.
CMD exec gunicorn --bind :$PORT --workers 2 --threads 8 --timeout 0 main:app
