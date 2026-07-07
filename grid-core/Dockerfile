# The Grid + Brain — Cloud Run image.
# Node 20 (better-sqlite3 native build needs python3/make/g++; @google-cloud/bigquery + others pure JS).
FROM node:20-bookworm-slim

WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends \
      python3 make g++ ca-certificates \
    && rm -rf /var/lib/apt/lists/*

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
