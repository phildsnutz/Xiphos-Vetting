FROM python:3.12-slim

# curl needed for Docker healthcheck
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend code (includes static/index.html frontend bundle)
COPY backend/ ./backend/

# Data directory for SQLite (mount a volume here for persistence)
RUN mkdir -p /data
ENV XIPHOS_DB_PATH=/data/xiphos.db
ENV XIPHOS_KG_DB_PATH=/data/xiphos_kg.db
ENV XIPHOS_SANCTIONS_DB=/data/sanctions.db

# Auth: enforce authentication in production
ENV XIPHOS_AUTH_ENABLED=true
# IMPORTANT: Override this with a real secret at deploy time
ENV XIPHOS_SECRET_KEY=CHANGE-ME-IN-PRODUCTION

# Skip sanctions sync on boot (run manually or via cron)
ENV XIPHOS_SKIP_SYNC=false

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD curl -f http://localhost:8080/api/health || exit 1

COPY docker-entrypoint.sh /app/docker-entrypoint.sh
RUN chmod +x /app/docker-entrypoint.sh

CMD ["/app/docker-entrypoint.sh"]
