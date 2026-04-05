# Load Balancer

Application-level reverse proxy and dashboard server.  
Routes external traffic to sensor pods using per-service round-robin, serves the
real-time Vue 3 dashboard, and exposes aggregated API endpoints for status,
readings, and scaler metrics.

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/dashboard` | Serves the single-page Vue 3 + Tailwind CSS dashboard. |
| `GET` | `/api/status` | Returns pod counts and IPs per sensor label + total pod count. |
| `GET` | `/api/readings` | Fetches the latest reading from one pod of each sensor (round-robin). |
| `GET` | `/api/scaler-status` | Proxies to the scaler's `/status` endpoint. Returns per-pod CPU, smoothed averages, cooldown timers, and window data. |
| `*` | `/{service}/{path}` | Reverse-proxy catch-all. Validates `service` against known sensor labels, selects the next pod via round-robin, and forwards the request. |

### Proxy Routing

Requests to `/{service}/{path}` are routed **only to pods belonging to that
service**. For example:

```
POST /sensor-temperature/stress?cpu_seconds=6
     → round-robin picks next sensor-temperature pod
     → forwards to http://<pod-ip>:8080/stress?cpu_seconds=6
```

The response includes an `X-Served-By` header with the pod IP that handled
the request.

## Components

### RoundRobinLB (`round_robin.py`)

Thread-safe load balancer state:

- `update_pods_by_label(label, ips)` — called by the pod-sync thread
- `next_pod_for_label(label)` — returns the next pod IP, advances the per-label index
- `get_pods_by_label()` — snapshot for the status API
- `get_labels()` — list of known sensor labels

### Pod Sync (`pod_sync.py`)

Background daemon thread that polls the Kubernetes API every N seconds
(default 5 s), discovers Running pods by `app=<label>` selector, and
updates the LB's pod lists. Filters out terminating pods.

### Dashboard (`static/index.html`)

Single-file Vue 3 application with Tailwind CSS:

- Polls `/api/status`, `/api/readings`, and `/api/scaler-status` every **1 second**
- Sensor cards show live readings with colour-coded thresholds (normal/warning/critical)
- Pod table shows per-sensor pod count, IPs, average CPU, and per-pod CPU values
- CPU values are colour-coded: green (< 30 %), amber (30–70 %), red (> 70 %)

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `APP_LABELS` | `sensor-temperature,sensor-humidity,sensor-energy,sensor-air-quality` | Comma-separated sensor labels to discover |
| `SYNC_INTERVAL` | `5` | Pod-sync polling interval in seconds |
| `LB_PORT` | `8080` | Port the LB listens on |
| `K8S_NAMESPACE` | `default` | Kubernetes namespace |
| `LOG_LEVEL` | `INFO` | Python log level |
| `SCALER_URL` | `http://scaler-svc:8081` | URL of the scaler's status API |

## Kubernetes Deployment

Deployment `load-balancer` with a NodePort Service:

- **NodePort**: 30080 → container port 8080
- Uses `scaler-sa` service account (needs pod list access)

Resource limits:

| | Request | Limit |
|---|---------|-------|
| CPU | 100m | 500m |
| Memory | 128Mi | 256Mi |

Probes:
- **Readiness** — `GET /api/status` every 10 s, initial delay 5 s
- **Liveness** — `GET /api/status` every 15 s, initial delay 10 s

## Docker Image

```dockerfile
FROM python:3.12-slim
CMD ["python", "main.py"]
```

Built inside Minikube:
```bash
minikube image build -p cloud-lb -t house-lb:latest ./lb
```

## Project Structure

```
lb/
├── main.py              # Entry point — starts pod-sync thread, runs uvicorn
├── round_robin.py       # RoundRobinLB class + FastAPI route definitions
├── pod_sync.py          # Background Kubernetes pod discovery thread
├── Dockerfile
├── requirements.txt     # fastapi, uvicorn, httpx, kubernetes
└── static/
    └── index.html       # Vue 3 + Tailwind CSS dashboard
```
