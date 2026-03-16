FROM python:3.12-slim

WORKDIR /app

# Install Python deps
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt gunicorn

# Copy backend code
COPY backend/ ./backend/

# Copy the bundled frontend
COPY dist/xiphos-dashboard.html ./static/index.html

# Data directory for SQLite (mount a volume here for persistence)
RUN mkdir -p /data
ENV XIPHOS_DB_PATH=/data/xiphos.db

EXPOSE 8080

# Sync sanctions lists on first boot, then start server
# Subsequent syncs can be triggered via POST /api/sanctions/sync
COPY docker-entrypoint.sh /app/docker-entrypoint.sh
RUN chmod +x /app/docker-entrypoint.sh

CMD ["/app/docker-entrypoint.sh"]
