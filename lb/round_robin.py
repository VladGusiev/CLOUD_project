import logging
import os
import threading
from datetime import datetime, timezone
from pathlib import Path

import httpx
from fastapi import FastAPI, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

logger = logging.getLogger("lb.round_robin")

STATIC_DIR = Path(__file__).parent / "static"

class RoundRobinLB:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._pods_by_label: dict[str, list[str]] = {}
        self._index_by_label: dict[str, int] = {}

    def update_pods_by_label(self, label: str, pod_ips: list[str]) -> None:
        """Replace the pod list for a specific sensor label."""
        with self._lock:
            self._pods_by_label[label] = list(pod_ips)
            if self._index_by_label.get(label, 0) >= len(pod_ips):
                self._index_by_label[label] = 0

    def next_pod_for_label(self, label: str) -> str | None:
        """Return the next pod IP for a given label in round-robin order."""
        with self._lock:
            pods = self._pods_by_label.get(label, [])
            if not pods:
                return None
            idx = self._index_by_label.get(label, 0) % len(pods)
            pod = pods[idx]
            self._index_by_label[label] = (idx + 1) % len(pods)
            return pod

    def get_pods_by_label(self) -> dict[str, list[str]]:
        """Return a snapshot of {label: [ip, ...]} mapping."""
        with self._lock:
            return {k: list(v) for k, v in self._pods_by_label.items()}

    def get_labels(self) -> list[str]:
        with self._lock:
            return list(self._pods_by_label.keys())


def create_app(lb: RoundRobinLB) -> FastAPI:
    app = FastAPI(title="House-Sensor Load Balancer")

    if STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    @app.get("/dashboard", include_in_schema=False)
    async def dashboard():
        index = STATIC_DIR / "index.html"
        if not index.exists():
            return Response("Dashboard not found", status_code=404)
        return FileResponse(str(index))

    @app.get("/api/status")
    async def api_status():
        pods_by_label = lb.get_pods_by_label()
        sensors: dict = {}
        total = 0
        for label, ips in pods_by_label.items():
            sensors[label] = {"pods": len(ips), "ips": ips}
            total += len(ips)
        return {
            "sensors": sensors,
            "total_pods": total,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    @app.get("/api/readings")
    async def api_readings():
        pods_by_label = lb.get_pods_by_label()
        readings: dict = {}

        async with httpx.AsyncClient(timeout=5.0) as client:
            for label in pods_by_label:
                pod_ip = lb.next_pod_for_label(label)
                if pod_ip is None:
                    readings[label] = None
                    continue
                try:
                    resp = await client.get(f"http://{pod_ip}:8080/sensor/reading")
                    resp.raise_for_status()
                    readings[label] = resp.json()
                except Exception as exc:
                    logger.warning("[LB] readings fetch failed for %s (%s): %s", label, pod_ip, exc)
                    readings[label] = None

        return readings

    SCALER_URL = os.environ.get("SCALER_URL", "http://scaler-svc:8081")

    @app.get("/api/scaler-status")
    async def api_scaler_status():
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                resp = await client.get(f"{SCALER_URL}/status")
                resp.raise_for_status()
                return resp.json()
        except Exception as exc:
            logger.warning("[LB] scaler-status fetch failed: %s", exc)
            return JSONResponse({"error": "scaler unreachable"}, status_code=502)

    @app.api_route("/{service}/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
    async def proxy(service: str, path: str, request: Request):
        """Route to a specific service's pods: /{sensor-label}/{endpoint}."""
        known_labels = lb.get_labels()
        if service not in known_labels:
            return JSONResponse(
                {"error": f"Unknown service '{service}'. Available: {known_labels}"},
                status_code=404,
            )

        pod_ip = lb.next_pod_for_label(service)

        if pod_ip is None:
            return JSONResponse(
                {"error": "No healthy pods available"},
                status_code=503,
            )

        target = f"http://{pod_ip}:8080/{path}"
        if request.query_params:
            target += f"?{request.url.query}"

        logger.info("[LB] %s -> %s | %s /%s", service, pod_ip, request.method, path)

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                body = await request.body()
                # Forward original headers except Host (httpx sets it)
                forward_headers = {
                    k: v for k, v in request.headers.items()
                    if k.lower() not in ("host", "content-length")
                }
                resp = await client.request(
                    method=request.method,
                    url=target,
                    content=body,
                    headers=forward_headers,
                )
        except httpx.TimeoutException:
            logger.error("[LB] timeout forwarding to %s", pod_ip)
            return JSONResponse({"error": "Upstream timeout"}, status_code=504)
        except httpx.RequestError as exc:
            logger.error("[LB] connection error to %s: %s", pod_ip, exc)
            return JSONResponse({"error": "Upstream unreachable"}, status_code=502)

        excluded = {"transfer-encoding", "connection", "keep-alive", "content-encoding"}
        response_headers = {
            k: v for k, v in resp.headers.items()
            if k.lower() not in excluded
        }
        # Add a header so callers can see which pod served the request
        response_headers["X-Served-By"] = pod_ip

        return Response(
            content=resp.content,
            status_code=resp.status_code,
            headers=response_headers,
            media_type=resp.headers.get("content-type"),
        )

    return app
