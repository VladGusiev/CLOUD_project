import hashlib
import os
import signal
import threading
import time
from contextlib import asynccontextmanager

import psutil
from fastapi import FastAPI, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    Counter,
    Gauge,
    generate_latest,
)

app_cpu_percent = Gauge("app_cpu_percent", "CPU utilization")
app_ram_bytes = Gauge("app_ram_bytes", "RAM usage")
app_active_requests = Gauge("app_active_requests", "Active requests")
app_requests_total = Counter("app_requests_total", "Total requests", ["status"])

_shutdown_event = threading.Event()

def _handle_sigterm(signum, frame):
    _shutdown_event.set()

signal.signal(signal.SIGTERM, _handle_sigterm)


class MetricsMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        app_active_requests.inc()
        try:
            response = await call_next(request)
            app_requests_total.labels(status=str(response.status_code)).inc()
            return response
        finally:
            app_active_requests.dec()


def create_app(title: str = "Sensor Microservice") -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield

    app = FastAPI(title=title, lifespan=lifespan)
    app.add_middleware(MetricsMiddleware)

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/metrics")
    def metrics():
        proc = psutil.Process(os.getpid())
        app_cpu_percent.set(psutil.cpu_percent(interval=0.1))
        app_ram_bytes.set(proc.memory_info().rss)
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    @app.post("/stress")
    def stress(cpu_seconds: float = 5.0, ram_mb: int = 64):
        blob = bytearray(ram_mb * 1024 * 1024)
        deadline = time.time() + cpu_seconds
        while time.time() < deadline:
            hashlib.sha256(blob[:1024]).hexdigest()
        return {"status": "done", "cpu_seconds": cpu_seconds, "ram_mb": ram_mb}

    return app
