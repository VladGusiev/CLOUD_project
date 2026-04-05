import asyncio
import logging

import aiohttp

logger = logging.getLogger(__name__)

METRICS_PORT = 8080
SCRAPE_TIMEOUT = 2.0


def parse_metrics(text: str) -> dict:
    """Parse Prometheus exposition format and return metric name → float value."""
    result = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) >= 2:
            name = parts[0]
            try:
                result[name] = float(parts[1])
            except ValueError:
                pass
    return result


async def scrape_pod(session: aiohttp.ClientSession, ip: str) -> dict | None:
    """Scrape /metrics from a single pod. Returns parsed metrics or None on error."""
    url = f"http://{ip}:{METRICS_PORT}/metrics"
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=SCRAPE_TIMEOUT)) as resp:
            if resp.status != 200:
                logger.warning("Pod %s returned HTTP %d", ip, resp.status)
                return None
            text = await resp.text()
            metrics = parse_metrics(text)
            return {
                "ip": ip,
                "cpu": metrics.get("app_cpu_percent", 0.0),
                "ram": metrics.get("app_ram_bytes", 0.0),
            }
    except Exception as e:
        logger.debug("Failed to scrape pod %s: %s", ip, e)
        return None


async def collect_metrics(k8s_client, app_label: str) -> dict:
    """
    Scrape all running pods for a single deployment and return aggregated metrics.

    Returns:
        {
            "avg_cpu": float,
            "avg_ram": float,
            "pod_count": int,
            "per_pod": [{"ip": str, "cpu": float, "ram": float}, ...]
        }
    """
    ips = k8s_client.get_running_pod_ips(app_label)

    if not ips:
        logger.warning("No running pods found for label: %s", app_label)
        return {"avg_cpu": 0.0, "avg_ram": 0.0, "pod_count": 0, "per_pod": []}

    async with aiohttp.ClientSession() as session:
        results = await asyncio.gather(*[scrape_pod(session, ip) for ip in ips])

    per_pod = [r for r in results if r is not None]

    if not per_pod:
        return {"avg_cpu": 0.0, "avg_ram": 0.0, "pod_count": 0, "per_pod": []}

    avg_cpu = sum(p["cpu"] for p in per_pod) / len(per_pod)
    avg_ram = sum(p["ram"] for p in per_pod) / len(per_pod)

    return {
        "avg_cpu": avg_cpu,
        "avg_ram": avg_ram,
        "pod_count": len(per_pod),
        "per_pod": per_pod,
    }
