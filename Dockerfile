FROM python:3.12-slim

WORKDIR /app

# Install Python deps
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt gunicorn

# Copy backend code
COPY backend/ ./backend/

# Copy the bundled frontend into backend/static/
COPY backend/static/index.html ./backend/static/index.html

# Data directory for SQLite (mount a volume here for persistence)
RUN mkdir -p /data
ENV XIPHOS_DB_PATH=/data/xiphos.db
ENV XIPHOS_KG_DB_PATH=/data/xiphos_kg.db
ENV XIPHOS_SANCTIONS_DB=/data/sanctions.db

# Auth: enforce authentication in production
ENV XIPHOS_AUTH_ENABLED=true
# IMPORTANT: Override this with a real secret at deploy time
ENV XIPHOS_SECRET_KEY=CHANGE-ME-IN-PRODUCTION

EXPOSE 8080

# Sync sanctions lists on first boot, then start server
COPY docker-entrypoint.sh /app/docker-entrypoint.sh
RUN chmod +x /app/docker-entrypoint.sh

CMD ["/app/docker-entrypoint.sh"]
