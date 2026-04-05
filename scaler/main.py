import asyncio
import logging
import os
import threading

import uvicorn
from fastapi import FastAPI

from k8s_client import K8sScalerClient
from scaler import ScalerConfig, ScalerManager

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("scaler.main")

_DEFAULT_LABELS = "sensor-temperature,sensor-humidity,sensor-energy,sensor-air-quality"

APP_LABELS: list[str] = [
    label.strip()
    for label in os.getenv("APP_LABELS", _DEFAULT_LABELS).split(",")
    if label.strip()
]
K8S_NAMESPACE: str = os.getenv("K8S_NAMESPACE", "default")


def _float_env(name: str, default: float) -> float:
    return float(os.getenv(name, str(default)))


def _int_env(name: str, default: int) -> int:
    return int(os.getenv(name, str(default)))


def _create_api(manager: ScalerManager) -> FastAPI:
    api = FastAPI(title="House-Sensor Scaler")

    @api.get("/status")
    async def status():
        return manager.get_status()

    return api


def main() -> None:
    config = ScalerConfig(
        scale_up_threshold=_float_env("SCALE_UP_THRESHOLD", 70.0),
        scale_down_threshold=_float_env("SCALE_DOWN_THRESHOLD", 30.0),
        min_replicas=_int_env("MIN_REPLICAS", 1),
        max_replicas=_int_env("MAX_REPLICAS", 5),
        cooldown_seconds=_float_env("COOLDOWN_SECONDS", 45.0),
        eval_interval_seconds=_float_env("EVAL_INTERVAL", 10.0),
        scrape_interval_seconds=_float_env("SCRAPE_INTERVAL", 10.0),
        metric_window_size=_int_env("METRIC_WINDOW_SIZE", 3),
    )

    logger.info("=== House-Sensor Scaler starting ===")
    logger.info("Labels    : %s", APP_LABELS)
    logger.info("Namespace : %s", K8S_NAMESPACE)
    logger.info("Thresholds: up=%.0f%% down=%.0f%%", config.scale_up_threshold, config.scale_down_threshold)
    logger.info("Replicas  : min=%d max=%d", config.min_replicas, config.max_replicas)
    logger.info("Cooldown  : %.0fs", config.cooldown_seconds)
    logger.info("Interval  : %.0fs", config.eval_interval_seconds)
    logger.info("Window    : %d samples", config.metric_window_size)

    k8s = K8sScalerClient(namespace=K8S_NAMESPACE)
    manager = ScalerManager(k8s_client=k8s, app_labels=APP_LABELS, config=config)

    api = _create_api(manager)
    api_port = _int_env("API_PORT", 8081)
    server = uvicorn.Server(uvicorn.Config(api, host="0.0.0.0", port=api_port, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    logger.info("Status API listening on :%d", api_port)

    asyncio.run(manager.run_loop())


if __name__ == "__main__":
    main()
