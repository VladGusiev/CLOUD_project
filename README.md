# Smart House — Dynamic Microservice Scaling on Kubernetes

A demonstration platform for **dynamic auto-scaling of microservices** on
Kubernetes. Four simulated smart-house sensors are deployed as independent
services; a custom control plane monitors their CPU utilisation and
automatically adjusts replica counts based on configurable thresholds.

## Architecture Overview

```
                        ┌─────────────────────────────────────────────────┐
                        │               Kubernetes Cluster                │
                        │                 (Minikube)                      │
                        │                                                 │
   Browser              │  ┌──────────────────┐    ┌──────────────────┐   │
  ┌──────────┐          │  │  Load Balancer    │    │    Scaler        │   │
  │Dashboard │◀────────▶│  │  (round-robin)    │◀──▶│  (control plane) │   │
  └──────────┘  :30080  │  │                   │    │                  │   │
                        │  │ /api/status       │    │ /status          │   │
                        │  │ /api/readings     │    │                  │   │
                        │  │ /api/scaler-status│    │  scrape /metrics │   │
                        │  │ /{service}/{path} │    │  PATCH replicas  │   │
                        │  └───────┬───────────┘    └────────┬─────────┘   │
                        │          │  round-robin            │  K8s API    │
                        │          ▼                         ▼             │
                        │  ┌─────────────┐  ┌─────────────┐               │
                        │  │ Temperature │  │  Humidity    │  ...×4       │
                        │  │  (1–5 pods) │  │  (1–5 pods) │               │
                        │  └─────────────┘  └─────────────┘               │
                        └─────────────────────────────────────────────────┘
```

### Services

| Service | Image | Port | Role |
|---------|-------|------|------|
| **Sensor Microservices** (×4) | `house-sensor` | 8080 | Simulated smart-house sensors (temperature, humidity, energy, air quality). Expose readings, Prometheus metrics, and a stress endpoint. |
| **Load Balancer** | `house-lb` | 8080 (NodePort 30080) | Per-service round-robin reverse proxy. Discovers pods via K8s API, serves the Vue 3 dashboard, aggregates readings and scaler status. |
| **Scaler** | `house-scaler` | 8081 | Custom auto-scaler. Scrapes pod metrics, applies threshold-based scaling with hysteresis and cooldown, exposes status API. |

Each service has its own detailed README:
- [`microservice/README.md`](microservice/README.md) — Sensor microservice
- [`lb/README.md`](lb/README.md) — Load balancer & dashboard
- [`scaler/README.md`](scaler/README.md) — Scaler (control plane)

## Quick Start

### Prerequisites

- [Minikube](https://minikube.sigs.k8s.io/) with Docker driver
- `kubectl`, `docker`, `curl`

### Start

```bash
./scripts/start-minikube.sh
```

This single script:
1. Creates an isolated Minikube profile (`cloud-lb`, 4 CPUs, 4 GB RAM)
2. Builds all three Docker images inside Minikube
3. Applies RBAC, deployments, and services
4. Waits for all pods to be ready
5. Sets up port-forwarding to `localhost:18080`

Once complete:
- **Dashboard** → http://127.0.0.1:18080/dashboard
- **API status** → http://127.0.0.1:18080/api/status
- **Scaler logs** → `kubectl --context cloud-lb logs -f deployment/scaler`

### Stop

```bash
./scripts/stop-minikube.sh
```

Tears down port-forwards and deletes the Minikube profile.

## Scaling Behaviour

The scaler evaluates each sensor deployment independently every **10 seconds**:

| Condition | Action |
|-----------|--------|
| Smoothed CPU ≥ 70 % | Scale up by 1 (max 5) |
| Smoothed CPU ≤ 30 % | Scale down by 1 (min 1) |
| 30 % < CPU < 70 % | No action (hysteresis) |

After any scale event, a **45-second cooldown** prevents oscillation.
CPU values are smoothed over a **3-sample sliding window** (30 s of data).

### CPU Normalisation

Sensor pods report CPU usage normalised against their **cgroup CPU limit**
(500m = 0.5 cores). This means 100 % CPU in the metrics corresponds to
the pod fully utilising its CPU allocation, regardless of the node's total
cores.

## Stress Testing

Two scripts are provided to generate load and observe scaling:

### Burn Test — single-pod saturation

```bash
./scripts/stess-test.sh [duration_s] [workers]  # default: 120s, 4 workers
```

Sends `POST /{sensor}/stress` requests through the LB. Each request burns
CPU for 6 seconds. **One worker saturates one pod** — scale up, then add
more workers to saturate new replicas.

### Flood Test — even load distribution

```bash
./scripts/stress-test-flood.sh [duration_s] [workers]  # default: 60s, 8 workers
```

Sends rapid-fire `GET /{sensor}/sensor/reading` requests. Because each
request completes in milliseconds, the round-robin distributes load
**evenly across all pods**, spiking CPU roughly equally.

Target a different sensor:
```bash
STRESS_TARGET=sensor-energy ./scripts/stess-test.sh 60 2
```

## Kubernetes Resources

```
k8s/
├── rbac.yaml                  # ServiceAccount, Role, RoleBinding for scaler
├── sensor-temperature.yaml    # Deployment + Service
├── sensor-humidity.yaml       # Deployment + Service
├── sensor-energy.yaml         # Deployment + Service
├── sensor-air-quality.yaml    # Deployment + Service
├── lb-deployment.yaml         # Deployment + NodePort Service
└── scaler-deployment.yaml     # Deployment + ClusterIP Service
```

### RBAC

The `scaler-sa` service account (used by both scaler and LB) has:
- `pods` — get, list, watch
- `deployments`, `deployments/scale` — get, list, patch, update

## Dashboard

The web dashboard (served at `/dashboard`) provides real-time visibility:

- **Sensor cards** — live readings with colour-coded thresholds (green/amber/red)
- **Pod table** — per-sensor replica count, pod IPs, average CPU, and per-pod CPU
- **Connection status** — health indicator, total pod count, last update timestamp

Refreshes every 1 second via three parallel API calls.

## Project Structure

```
.
├── README.md                    # ← You are here
├── microservice/                # Sensor pods (shared image)
│   ├── base_app.py              # FastAPI factory, metrics, stress endpoint
│   ├── sensors/                 # temperature, humidity, energy, air_quality
│   ├── test_sensors.py          # Local integration tests
│   ├── Dockerfile
│   └── requirements.txt
├── lb/                          # Load balancer + dashboard
│   ├── main.py                  # Entry point
│   ├── round_robin.py           # LB logic + API routes
│   ├── pod_sync.py              # K8s pod discovery thread
│   ├── static/index.html        # Vue 3 dashboard
│   ├── Dockerfile
│   └── requirements.txt
├── scaler/                      # Custom auto-scaler
│   ├── main.py                  # Entry point + status API
│   ├── scaler.py                # Threshold logic + manager
│   ├── monitor.py               # Prometheus scraper
│   ├── k8s_client.py            # K8s API wrapper
│   ├── metrics_window.py        # Sliding window
│   ├── Dockerfile
│   └── requirements.txt
├── k8s/                         # Kubernetes manifests
├── scripts/
│   ├── start-minikube.sh        # One-command cluster setup
│   ├── stop-minikube.sh         # Cluster teardown
│   ├── stess-test.sh            # CPU burn stress test
│   └── stress-test-flood.sh     # High-frequency flood test
└── docs/
    └── implementation_plan.md
```

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Language | Python 3.12 |
| Web framework | FastAPI + Uvicorn |
| Metrics | Prometheus client library |
| HTTP clients | httpx (LB), aiohttp (scaler) |
| Container runtime | Docker |
| Orchestration | Kubernetes (Minikube) |
| Frontend | Vue 3, Tailwind CSS |


```

## Docker

```bash
# Build the image
cd ROOT-PROJECT
docker build -t house-sensor:latest ./microservice

# Run temperature sensor
docker run --rm -e SENSOR_TYPE=temperature -p 8080:8080 house-sensor:latest

# Test (in another terminal)
curl http://localhost:8080/health
curl http://localhost:8080/sensor/reading
curl http://localhost:8080/metrics

# Run a different sensor on a different port
docker run --rm -e SENSOR_TYPE=humidity -p 8081:8080 house-sensor:latest
curl http://localhost:8081/sensor/reading
# Expected: {"type":"humidity","value":...,"unit":"%"}


```

## Kubernetes Run (Minikube)

```bash
# Start Minikube
minikube start --driver=docker --cpus=4 --memory=4096
# Build image inside Minikube
eval $(minikube docker-env)
docker build -t house-sensor:latest ./microservice
# Deploy all 4 sensors
kubectl apply -f k8s/sensor-temperature.yaml \
              -f k8s/sensor-humidity.yaml \
              -f k8s/sensor-energy.yaml \
              -f k8s/sensor-air-quality.yaml
# Wait for pods to be ready
kubectl get pods -l component=sensor -w
# Wait until all 4 show 1/1 Running
# Port-forward and test any sensor
kubectl port-forward deployment/sensor-temperature 8080:8080
curl http://localhost:8080/health
curl http://localhost:8080/sensor/reading
curl http://localhost:8080/metrics
curl -X POST "http://localhost:8080/stress?cpu_seconds=5&ram_mb=64"
```
