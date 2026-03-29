FROM python:3.12-slim

# curl needed for Docker healthcheck; ca-certificates keeps outbound TLS trust current
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    && update-ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend code (includes static/index.html frontend bundle)
COPY backend/ ./backend/

# Data directory for SQLite (mount a volume here for persistence)
# Set HELIOS_DB_ENGINE=postgres and XIPHOS_PG_URL for PostgreSQL
RUN mkdir -p /data /data/cache /data/ml/model /app/ml /app/scripts
ENV XIPHOS_DATA_DIR=/data

# Auth: enforce authentication in production
ENV XIPHOS_AUTH_ENABLED=true

# Skip sanctions sync on boot (run manually or via cron)
ENV XIPHOS_SKIP_SYNC=false

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD curl -f http://localhost:8080/api/health || exit 1

COPY ml/__init__.py ./ml/__init__.py
COPY ml/inference.py ./ml/inference.py
COPY scripts/run_full_system_test.py /app/scripts/run_full_system_test.py
COPY docker-entrypoint.sh /app/docker-entrypoint.sh
RUN chmod +x /app/docker-entrypoint.sh

CMD ["/app/docker-entrypoint.sh"]
