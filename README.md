# House Sensor Microservices

## Local Run

```bash
cd microservice
python3 -m venv .venv
source .venv/bin/activate  # or .venv/bin/activate.fish
pip install -r requirements.txt

--------
python3 test_sensors.py
--------

uvicorn sensors.temperature:app --host 127.0.0.1 --port 8080
# 1. Health check (K8s probe simulation)
curl http://localhost:8080/health
# Expected: {"status":"ok"}

# 2. Sensor reading
curl http://localhost:8080/sensor/reading
# Expected: {"type":"temperature","value":22.4,"unit":"°C"}  (value varies)

# 3. Prometheus metrics
curl http://localhost:8080/metrics
# Expected: Prometheus text lines including app_cpu_percent, app_ram_bytes, etc.

# 4. Stress endpoint — generates CPU + RAM load
curl -X POST "http://localhost:8080/stress?cpu_seconds=5&ram_mb=64"
# Expected: {"status":"done","cpu_seconds":5.0,"ram_mb":64}  (takes ~5s)


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
