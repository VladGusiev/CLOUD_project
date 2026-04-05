import logging
import time

from kubernetes import client, config
from kubernetes.client.rest import ApiException

logger = logging.getLogger(__name__)


class K8sScalerClient:
    """Wrapper around the Kubernetes API for reading and adjusting deployments."""

    def __init__(self, namespace: str = "default"):
        self.namespace = namespace
        try:
            config.load_incluster_config()
            logger.info("Loaded in-cluster K8s config")
        except config.ConfigException:
            config.load_kube_config()
            logger.info("Loaded local kubeconfig")

        self._apps = client.AppsV1Api()
        self._core = client.CoreV1Api()

    def get_replicas(self, deployment_name: str) -> int:
        """Return current ready replica count for a deployment."""
        deployment = self._apps.read_namespaced_deployment(
            name=deployment_name,
            namespace=self.namespace,
        )
        return deployment.spec.replicas or 0

    def scale(self, deployment_name: str, replicas: int, retries: int = 3) -> None:
        """Set replica count for a deployment with exponential backoff on conflict."""
        body = {"spec": {"replicas": replicas}}
        delay = 1.0
        for attempt in range(retries):
            try:
                self._apps.patch_namespaced_deployment_scale(
                    name=deployment_name,
                    namespace=self.namespace,
                    body=body,
                )
                logger.info("Scaled %s to %d replicas", deployment_name, replicas)
                return
            except ApiException as e:
                if e.status == 409 and attempt < retries - 1:
                    logger.warning(
                        "Conflict scaling %s, retrying in %.1fs (attempt %d/%d)",
                        deployment_name, delay, attempt + 1, retries,
                    )
                    time.sleep(delay)
                    delay *= 2
                else:
                    raise

    def get_running_pod_ips(self, app_label: str) -> list[str]:
        """Return IPs of all Running, non-terminating pods for a given app label."""
        pods = self._core.list_namespaced_pod(
            namespace=self.namespace,
            label_selector=f"app={app_label}",
        )
        ips = []
        for pod in pods.items:
            if (
                pod.status.phase == "Running"
                and pod.status.pod_ip
                and pod.metadata.deletion_timestamp is None
            ):
                ips.append(pod.status.pod_ip)
        return ips
