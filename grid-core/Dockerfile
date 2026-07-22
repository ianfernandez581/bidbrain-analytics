# The Grid + Brain — Cloud Run image.
# Node 20 (better-sqlite3 native build needs python3/make/g++; @google-cloud/bigquery + others pure JS).
FROM node:20-bookworm-slim

WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends \
      python3 python3-pip make g++ ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && pip3 install --no-cache-dir --break-system-packages google-cloud-storage
# ^ python3 + google-cloud-storage let the server spawn scripts/build_exec_kpis.py --stdout to refresh
#   the Executive tab's live KPIs from each client's data.json (ADC = the Cloud Run runtime SA).

# Install deps first for layer caching. package-lock.json is committed.
COPY package.json package-lock.json ./
RUN npm ci --omit=dev

# App source (node_modules, tmp, data, .env excluded via .dockerignore)
COPY . .

# Cloud Run sets PORT=8080; SQLite staging + uploads go to the writable /tmp.
ENV NODE_ENV=production \
    PORT=8080 \
    BRAIN_DATA_DIR=/tmp/brain-data \
    BRAIN_TMP_DIR=/tmp/brain-uploads

EXPOSE 8080
CMD ["node", "server.js"]
