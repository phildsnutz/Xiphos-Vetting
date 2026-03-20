import os


workers = int(os.environ.get("XIPHOS_GUNICORN_WORKERS", "1"))
threads = int(os.environ.get("XIPHOS_GUNICORN_THREADS", "4"))
timeout = int(os.environ.get("XIPHOS_GUNICORN_TIMEOUT", "300"))
graceful_timeout = int(os.environ.get("XIPHOS_GUNICORN_GRACEFUL_TIMEOUT", "30"))
keepalive = int(os.environ.get("XIPHOS_GUNICORN_KEEPALIVE", "5"))
accesslog = "-"
errorlog = "-"
capture_output = True
loglevel = os.environ.get("XIPHOS_LOG_LEVEL", "info").lower()
