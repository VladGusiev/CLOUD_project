import asyncio
import logging
import time
from dataclasses import dataclass

from k8s_client import K8sScalerClient
from metrics_window import MetricWindow
from monitor import collect_metrics

logger = logging.getLogger("scaler.scaler")


@dataclass
class ScalerConfig:
    scale_up_threshold: float = 70.0
    scale_down_threshold: float = 30.0
    min_replicas: int = 1
    max_replicas: int = 5
    cooldown_seconds: float = 45.0
    eval_interval_seconds: float = 10.0
    scrape_interval_seconds: float = 10.0
    metric_window_size: int = 3


class ThresholdScaler:
    """Per-deployment scaler with hysteresis and cooldown."""

    def __init__(self, deployment_name: str, config: ScalerConfig) -> None:
        self.deployment_name = deployment_name
        self.config = config
        self._last_scale_time: float = 0.0

    def _in_cooldown(self) -> bool:
        elapsed = time.time() - self._last_scale_time
        return elapsed < self.config.cooldown_seconds

    def cooldown_remaining(self) -> float:
        remaining = self.config.cooldown_seconds - (time.time() - self._last_scale_time)
        return max(0.0, remaining)

    def evaluate(self, avg_cpu: float, current_replicas: int) -> int | None:
        """Return desired replica count, or None if no action needed."""
        if avg_cpu >= self.config.scale_up_threshold:
            desired = current_replicas + 1
        elif avg_cpu <= self.config.scale_down_threshold:
            desired = current_replicas - 1
        else:
            return None

        desired = max(self.config.min_replicas, min(self.config.max_replicas, desired))
        if desired == current_replicas:
            return None
        return desired

    def record_scale(self) -> None:
        self._last_scale_time = time.time()


class ScalerManager:
    """Manages threshold scalers for multiple deployments."""

    def __init__(
        self,
        k8s_client: K8sScalerClient,
        app_labels: list[str],
        config: ScalerConfig,
    ) -> None:
        self.k8s = k8s_client
        self.app_labels = app_labels
        self.config = config
        self._scalers: dict[str, ThresholdScaler] = {
            label: ThresholdScaler(label, config) for label in app_labels
        }
        self._windows: dict[str, MetricWindow] = {
            label: MetricWindow(size=config.metric_window_size) for label in app_labels
        }
        self._last_metrics: dict[str, dict] = {}

    async def _evaluate_deployment(self, label: str) -> None:
        scaler = self._scalers[label]
        window = self._windows[label]

        metrics = await collect_metrics(self.k8s, label)
        avg_cpu = metrics["avg_cpu"]
        pod_count = metrics["pod_count"]
        per_pod = metrics["per_pod"]
        pod_cpus = [round(p["cpu"], 1) for p in per_pod]

        self._last_metrics[label] = metrics

        window.add(avg_cpu)
        smoothed_cpu = window.average()

        if not window.is_full():
            logger.info(
                "[WARMING] %s: collecting samples (%d/%d), avg_cpu=%.1f%%, per_pod=%s",
                label, len(window), window._window.maxlen, smoothed_cpu, pod_cpus,
            )
            return

        current_replicas = self.k8s.get_replicas(label)
        desired = scaler.evaluate(smoothed_cpu, current_replicas)

        if desired is None:
            logger.info(
                "[STABLE] %s: no action (avg_cpu=%.1f%%, replicas=%d, per_pod=%s)",
                label, smoothed_cpu, current_replicas, pod_cpus,
            )
            return

        if scaler._in_cooldown():
            logger.info(
                "[COOLDOWN] %s: skipping (%.0fs remaining, avg_cpu=%.1f%%, per_pod=%s)",
                label, scaler.cooldown_remaining(), smoothed_cpu, pod_cpus,
            )
            return

        self.k8s.scale(label, desired)
        scaler.record_scale()
        logger.info(
            "[SCALE] %s: %d → %d (avg_cpu=%.1f%%, window=%s, per_pod=%s)",
            label, current_replicas, desired, smoothed_cpu,
            [round(v, 1) for v in window.values()],
            pod_cpus,
        )

    def get_status(self) -> dict:
        """Return the current scaler state for all deployments."""
        result = {}
        for label in self.app_labels:
            scaler = self._scalers[label]
            window = self._windows[label]
            metrics = self._last_metrics.get(label, {})
            per_pod = metrics.get("per_pod", [])

            result[label] = {
                "avg_cpu": round(metrics.get("avg_cpu", 0.0), 1),
                "smoothed_cpu": round(window.average(), 1),
                "replicas": metrics.get("pod_count", 0),
                "cooldown_remaining": round(scaler.cooldown_remaining(), 1),
                "window": [round(v, 1) for v in window.values()],
                "per_pod": [
                    {"ip": p["ip"], "cpu": round(p["cpu"], 1)}
                    for p in per_pod
                ],
            }
        return result

    async def run_loop(self) -> None:
        logger.info(
            "[scaler] Starting main loop — labels=%s, thresholds=%.0f%%/%.0f%%, "
            "cooldown=%.0fs, interval=%.0fs, window=%d",
            self.app_labels,
            self.config.scale_up_threshold,
            self.config.scale_down_threshold,
            self.config.cooldown_seconds,
            self.config.eval_interval_seconds,
            self.config.metric_window_size,
        )

        while True:
            for label in self.app_labels:
                try:
                    await self._evaluate_deployment(label)
                except Exception as exc:
                    logger.error("[scaler] Error evaluating %s: %s", label, exc, exc_info=True)

            logger.info("---")
            await asyncio.sleep(self.config.eval_interval_seconds)
