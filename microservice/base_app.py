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


def _get_cpu_limit_cores() -> float:
    """Detect cgroup CPU limit (works inside K8s containers).
    Returns the CPU allocation in cores (e.g. 500m → 0.5)."""
    # cgroup v2
    try:
        with open("/sys/fs/cgroup/cpu.max") as f:
            parts = f.read().strip().split()
            if parts[0] != "max":
                return int(parts[0]) / int(parts[1])
    except (FileNotFoundError, ValueError, IndexError):
        pass
    # cgroup v1
    try:
        with open("/sys/fs/cgroup/cpu/cpu.cfs_quota_us") as f:
            quota = int(f.read().strip())
        if quota != -1:
            with open("/sys/fs/cgroup/cpu/cpu.cfs_period_us") as f:
                period = int(f.read().strip())
            return quota / period
    except (FileNotFoundError, ValueError):
        pass
    # No limit detected — assume all system CPUs available
    return float(os.cpu_count() or 1)


def create_app(title: str = "Sensor Microservice") -> FastAPI:
    # Background thread updates CPU/RAM gauges every 1s so /metrics is never
    # blocked by in-flight stress requests and always returns fresh data.
    _proc = psutil.Process(os.getpid())
    # Prime the per-process CPU tracker (first call always returns 0.0)
    _proc.cpu_percent()
    _cpu_limit = _get_cpu_limit_cores()

    def _metrics_updater() -> None:
        while not _shutdown_event.is_set():
            try:
                raw = _proc.cpu_percent()
                # Normalize: raw is % of one core; cpu_limit is in cores.
                # e.g. raw=50%, limit=0.5 cores → 50/(0.5*100)*100 = 100%
                normalized = min(100.0, raw / (_cpu_limit * 100) * 100)
                app_cpu_percent.set(normalized)
                app_ram_bytes.set(_proc.memory_info().rss)
            except Exception:
                pass
            _shutdown_event.wait(timeout=1.0)

    _metrics_thread = threading.Thread(target=_metrics_updater, daemon=True, name="metrics-updater")
    _metrics_thread.start()

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
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    @app.post("/stress")
    def stress(cpu_seconds: float = 5.0, ram_mb: int = 64):
        blob = bytearray(ram_mb * 1024 * 1024)
        deadline = time.time() + cpu_seconds
        while time.time() < deadline:
            hashlib.sha256(blob[:1024]).hexdigest()
        return {"status": "done", "cpu_seconds": cpu_seconds, "ram_mb": ram_mb}

    return app
