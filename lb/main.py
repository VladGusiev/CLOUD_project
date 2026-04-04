import logging
import os

import uvicorn

from pod_sync import start_sync_thread
from round_robin import RoundRobinLB, create_app

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger("lb.main")

_DEFAULT_LABELS = "sensor-temperature,sensor-humidity,sensor-energy,sensor-air-quality"

APP_LABELS: list[str] = [
    label.strip()
    for label in os.getenv("APP_LABELS", _DEFAULT_LABELS).split(",")
    if label.strip()
]
SYNC_INTERVAL: float = float(os.getenv("SYNC_INTERVAL", "5"))
LB_PORT: int = int(os.getenv("LB_PORT", "8080"))
K8S_NAMESPACE: str = os.getenv("K8S_NAMESPACE", "default")

def main() -> None:
    logger.info("=== House-Sensor Load Balancer starting ===")
    logger.info("Labels   : %s", APP_LABELS)
    logger.info("Namespace: %s", K8S_NAMESPACE)
    logger.info("Sync     : %.1fs interval", SYNC_INTERVAL)
    logger.info("Port     : %d", LB_PORT)

    lb = RoundRobinLB()

    sync_thread = start_sync_thread(
        lb=lb,
        app_labels=APP_LABELS,
        namespace=K8S_NAMESPACE,
        interval=SYNC_INTERVAL,
    )
    logger.info("Pod sync thread started (tid=%s)", sync_thread.name)

    app = create_app(lb)

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=LB_PORT,
        log_level=LOG_LEVEL.lower(),
        access_log=False,  # We do our own per-request logging in the proxy
    )


if __name__ == "__main__":
    main()
