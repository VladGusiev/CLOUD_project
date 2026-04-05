# Scaler (Control Plane)

Custom Kubernetes auto-scaler that monitors sensor pod CPU utilisation and
adjusts replica counts using threshold-based scaling with hysteresis and
cooldown protection.

## How It Works

```
┌──────────┐     scrape /metrics     ┌────────────┐
│  Sensor  │◀────────────────────────│   Scaler   │
│   Pods   │  (every eval_interval)  │            │
└──────────┘                         │  ┌───────┐ │    K8s API
                                     │  │Window │ │───────────▶ PATCH
                                     │  │(avg)  │ │   scale
                                     │  └───────┘ │
                                     └────────────┘
```

1. **Scrape** — For each deployment, fetch `/metrics` from all Running pods via `aiohttp`
2. **Smooth** — Feed `avg_cpu` into a sliding window (default 3 samples = 30 s of data)
3. **Evaluate** — Compare smoothed CPU against thresholds:
   - `≥ 70 %` → scale up by 1 replica
   - `≤ 30 %` → scale down by 1 replica
   - Between 30–70 % → no action (hysteresis band)
4. **Scale** — Patch the deployment's replica count via the Kubernetes API
5. **Cooldown** — After any scale action, wait 45 s before allowing another

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/status` | Returns the current scaler state for all deployments (JSON) |

### `/status` Response Format

```json
{
  "sensor-temperature": {
    "avg_cpu": 65.3,
    "smoothed_cpu": 58.7,
    "replicas": 2,
    "cooldown_remaining": 12.4,
    "window": [45.2, 65.3, 65.5],
    "per_pod": [
      {"ip": "10.244.0.5", "cpu": 95.2},
      {"ip": "10.244.0.8", "cpu": 2.1}
    ]
  },
  "sensor-humidity": { ... },
  "sensor-energy": { ... },
  "sensor-air-quality": { ... }
}
```

| Field | Description |
|-------|-------------|
| `avg_cpu` | Raw average CPU across all pods from the last scrape |
| `smoothed_cpu` | Sliding-window average used for scaling decisions |
| `replicas` | Number of pods that responded to the last scrape |
| `cooldown_remaining` | Seconds until scaling is allowed again (0 = ready) |
| `window` | All samples in the sliding window |
| `per_pod` | Per-pod IP and normalised CPU percentage |

## Architecture

### ScalerConfig

Dataclass holding all tuning parameters. Every field is configurable via
environment variables.

### ThresholdScaler

Per-deployment evaluator. Tracks cooldown state and applies the threshold
logic with hysteresis.

### ScalerManager

Main orchestrator:
- Holds one `ThresholdScaler` and one `MetricWindow` per deployment
- Runs an async loop: scrape → smooth → evaluate → scale
- Exposes `get_status()` for the HTTP API

### K8sScalerClient

Kubernetes API wrapper:
- `get_replicas(deployment)` — reads current spec.replicas
- `scale(deployment, n)` — patches replica count with exponential backoff on 409 Conflict
- `get_running_pod_ips(label)` — lists Running, non-terminating pod IPs

### MetricWindow

`collections.deque`-based sliding window with `add()`, `average()`,
`is_full()`, `values()`, and `len()` support.

### Monitor

Async scraper:
- `scrape_pod(session, ip)` — fetches `/metrics`, parses Prometheus format
- `collect_metrics(k8s_client, label)` — scrapes all pods for a deployment,
  returns `avg_cpu`, `avg_ram`, `pod_count`, and `per_pod` details

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `APP_LABELS` | `sensor-temperature,sensor-humidity,sensor-energy,sensor-air-quality` | Deployments to monitor |
| `K8S_NAMESPACE` | `default` | Kubernetes namespace |
| `SCALE_UP_THRESHOLD` | `70` | CPU % above which to add a replica |
| `SCALE_DOWN_THRESHOLD` | `30` | CPU % below which to remove a replica |
| `MIN_REPLICAS` | `1` | Floor for replica count |
| `MAX_REPLICAS` | `5` | Ceiling for replica count |
| `COOLDOWN_SECONDS` | `45` | Seconds to wait after a scale action |
| `EVAL_INTERVAL` | `10` | Seconds between evaluation cycles |
| `METRIC_WINDOW_SIZE` | `3` | Number of samples in the smoothing window |
| `LOG_LEVEL` | `INFO` | Python log level |
| `API_PORT` | `8081` | Port for the status HTTP API |

## Log Format

Each evaluation cycle produces one log line per deployment:

```
[WARMING]  sensor-temperature: collecting samples (1/3), avg_cpu=12.0%, per_pod=[12.0]
[STABLE]   sensor-temperature: no action (avg_cpu=45.2%, replicas=2, per_pod=[40.1, 50.3])
[COOLDOWN] sensor-temperature: skipping (23s remaining, avg_cpu=81.0%, per_pod=[100.0, 62.0])
[SCALE]    sensor-temperature: 1 → 2 (avg_cpu=85.3%, window=[70.1, 85.3, 90.5], per_pod=[85.3])
```

Cycles are separated by `---`.

## Kubernetes Deployment

Deployment `scaler` with a ClusterIP Service `scaler-svc`:

- **Service port**: 8081 (status API, accessed by the LB)
- Uses `scaler-sa` service account

RBAC permissions (via `rbac.yaml`):
- `pods` — get, list, watch (to discover pod IPs and scrape metrics)
- `deployments`, `deployments/scale` — get, list, patch, update (to read/set replica counts)

Resource limits:

| | Request | Limit |
|---|---------|-------|
| CPU | 50m | 200m |
| Memory | 64Mi | 128Mi |

## Docker Image

```dockerfile
FROM python:3.12-slim
CMD ["python", "main.py"]
```

Built inside Minikube:
```bash
minikube image build -p cloud-lb -t house-scaler:latest ./scaler
```

## Project Structure

```
scaler/
├── main.py              # Entry point — config, FastAPI status server, async loop
├── scaler.py            # ScalerConfig, ThresholdScaler, ScalerManager
├── monitor.py           # Async Prometheus scraper
├── k8s_client.py        # Kubernetes API wrapper (replicas, scale, pod IPs)
├── metrics_window.py    # Sliding window for metric smoothing
├── Dockerfile
└── requirements.txt     # kubernetes, aiohttp, prometheus_client, fastapi, uvicorn
```
