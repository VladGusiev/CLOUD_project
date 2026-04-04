import logging
import threading
import time

from kubernetes import client, config

logger = logging.getLogger("lb.pod_sync")


def _load_k8s_config() -> None:
    """Try in-cluster config first, fall back to local kubeconfig."""
    try:
        config.load_incluster_config()
        logger.info("[pod_sync] Using in-cluster Kubernetes config")
    except config.ConfigException:
        config.load_kube_config()
        logger.info("[pod_sync] Using local kubeconfig")


def _get_running_pod_ips(core_api: client.CoreV1Api, app_label: str, namespace: str) -> list[str]:
    """Return IPs of pods that are Running, have an IP, and are not terminating."""
    pods = core_api.list_namespaced_pod(
        namespace=namespace,
        label_selector=f"app={app_label}",
    )
    ips: list[str] = []
    for pod in pods.items:
        meta = pod.metadata
        status = pod.status
        # Skip pods that are being deleted
        if meta.deletion_timestamp is not None:
            continue
        # Must be Running with an assigned IP
        if status.phase == "Running" and status.pod_ip:
            ips.append(status.pod_ip)
    return ips


def sync_pods_loop(
    lb,
    app_labels: list[str],
    namespace: str = "default",
    interval: float = 5.0,
) -> None:
    _load_k8s_config()
    core_api = client.CoreV1Api()

    logger.info(
        "[pod_sync] Starting sync loop — labels=%s, interval=%.1fs, namespace=%s",
        app_labels,
        interval,
        namespace,
    )

    while True:
        try:
            all_ips: list[str] = []

            for label in app_labels:
                ips = _get_running_pod_ips(core_api, label, namespace)
                lb.update_pods_by_label(label, ips)
                all_ips.extend(ips)
                logger.debug("[pod_sync] %s → %d pod(s): %s", label, len(ips), ips)

            lb.update_pods(all_ips)
            logger.info(
                "[pod_sync] Synced %d total pod(s) across %d label(s)",
                len(all_ips),
                len(app_labels),
            )

        except Exception as exc:
            # Never crash the daemon — log and retry next cycle
            logger.error("[pod_sync] Sync error: %s", exc, exc_info=True)

        time.sleep(interval)


def start_sync_thread(lb, app_labels: list[str], namespace: str = "default", interval: float = 5.0) -> threading.Thread:
    """Spawn and return the pod sync daemon thread."""
    t = threading.Thread(
        target=sync_pods_loop,
        args=(lb, app_labels, namespace, interval),
        daemon=True,
        name="pod-sync",
    )
    t.start()
    return t
