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


def post_fork(server, worker):
    if os.environ.get("XIPHOS_ENABLE_GRAPH_PREWARM", "true").lower() == "true":
        try:
            from server import _start_graph_prewarm_async

            if _start_graph_prewarm_async():
                server.log.info("Graph runtime prewarm started in worker %s", worker.pid)
        except Exception as exc:
            server.log.warning("Failed to start graph runtime prewarm: %s", exc)

    if os.environ.get("XIPHOS_ENABLE_PERIODIC_MONITORING", "false").lower() != "true":
        return
    effective_workers = int(getattr(getattr(server, "cfg", None), "workers", workers) or workers)
    if effective_workers != 1:
        server.log.warning(
            "Periodic monitoring requested but disabled because gunicorn is running %s workers. "
            "Set XIPHOS_GUNICORN_WORKERS=1 or disable periodic monitoring.",
            effective_workers,
        )
        return
    try:
        from server import _maybe_start_periodic_monitoring

        _maybe_start_periodic_monitoring()
        server.log.info("Periodic monitoring scheduler started in worker %s", worker.pid)
    except Exception as exc:
        server.log.warning("Failed to start periodic monitoring scheduler: %s", exc)
