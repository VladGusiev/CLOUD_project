# Sensor Microservice

Simulated smart-house sensors deployed as independent Kubernetes pods.
All four sensor types share a single Docker image (`house-sensor`); the
`SENSOR_TYPE` environment variable selects the behaviour at startup.

## Sensor Types

| Type | Module | Reading endpoint | Values |
|------|--------|-----------------|--------|
| Temperature | `sensors.temperature` | `GET /sensor/reading` | `value` 18–28 °C |
| Humidity | `sensors.humidity` | `GET /sensor/reading` | `value` 30–80 % |
| Energy | `sensors.energy` | `GET /sensor/reading` | `value` 0.5–15 kW |
| Air Quality | `sensors.air_quality` | `GET /sensor/reading` | `co2_ppm` 400–2000, `pm25` 5–150 |

Each reading is randomly generated on every request.

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Returns `{"status": "ok"}`. Used by K8s liveness/readiness probes. |
| `GET` | `/sensor/reading` | Returns a JSON reading specific to the sensor type. |
| `GET` | `/metrics` | Prometheus exposition format with `app_cpu_percent`, `app_ram_bytes`, `app_active_requests`, `app_requests_total`, and sensor-specific gauges. |
| `POST` | `/stress?cpu_seconds=5&ram_mb=64` | Burns CPU for the given duration; allocates the given amount of RAM. Used for testing the scaler. |

## Metrics & CPU Measurement

CPU is measured **per-process** via `psutil.Process.cpu_percent()` in a
background thread that updates every 1 second. The raw value is normalised
against the container's cgroup CPU limit:

```
normalised = raw_percent / (cpu_limit_cores × 100) × 100
```

For example, with a Kubernetes limit of `500m` (0.5 cores):

- Idle → ~0 %
- Full single-thread burn → ~100 %

cgroup v1 and v2 quota files are both supported.

## Configuration

All configuration is via environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `SENSOR_TYPE` | `temperature` | Which sensor module to load (`temperature`, `humidity`, `energy`, `air_quality`) |

## Kubernetes Deployment

Each sensor type has its own Deployment + ClusterIP Service:

- `sensor-temperature` / `sensor-temperature-svc`
- `sensor-humidity` / `sensor-humidity-svc`
- `sensor-energy` / `sensor-energy-svc`
- `sensor-air-quality` / `sensor-air-quality-svc`

Resource limits per pod:

| | Request | Limit |
|---|---------|-------|
| CPU | 100m | 500m |
| Memory | 128Mi | 256Mi |

Probes:
- **Readiness** — `GET /health` every 5 s, initial delay 3 s
- **Liveness** — `GET /health` every 10 s, initial delay 5 s

## Docker Image

```dockerfile
FROM python:3.12-slim
# Selected at runtime via SENSOR_TYPE env var
CMD ["sh", "-c", "uvicorn sensors.${SENSOR_TYPE}:app --host 0.0.0.0 --port 8080"]
```

Built inside Minikube:
```bash
minikube image build -p cloud-lb -t house-sensor:latest ./microservice
```

## Local Testing

```bash
cd microservice
python test_sensors.py
```

Starts all four sensor types on ports 18080–18083, runs health/reading/stress/metrics
checks, and exits with a pass/fail summary.

## Project Structure

```
microservice/
├── base_app.py          # Shared FastAPI app factory, metrics middleware, stress endpoint
├── Dockerfile
├── requirements.txt     # fastapi, uvicorn, prometheus_client, psutil
├── test_sensors.py      # Integration test runner
└── sensors/
    ├── __init__.py
    ├── temperature.py
    ├── humidity.py
    ├── energy.py
    └── air_quality.py
```
