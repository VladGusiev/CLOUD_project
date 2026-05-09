# Dynamic Microservice Scaling on Kubernetes

## 1. Introduction

This project demonstrates dynamic horizontal scaling of microservices running on Kubernetes. The system simulates a smart-house environment where four sensor services generate data, a load balancer distributes incoming requests, and a custom auto-scaler adjusts the number of running instances based on real-time CPU utilisation. The entire platform is deployed on a local Minikube cluster and includes a web dashboard for live monitoring.

## 2. System Architecture

The system consists of five components: the **sensor microservices** (data plane), the **load balancer** (entry point and traffic distribution), the **scaler** (control plane), **Prometheus** (metrics collection), and **Grafana** (metrics visualisation). All components run as containerised applications inside Kubernetes.

External users interact with the system through the load balancer, which serves a web dashboard and forwards API requests to the appropriate sensor pods. The scaler runs independently in the background — it periodically collects metrics from each sensor deployment and decides whether to increase or decrease the number of replicas. Prometheus scrapes metrics from every sensor pod and from the scaler itself, and Grafana provides a pre-provisioned dashboard that visualises those metrics in real time.

The sensor microservices, the load balancer, and the scaler are each packaged as separate Docker images built from Python 3.12 applications using the FastAPI framework.

## 3. Sensor Microservices

The data plane consists of four sensor types: temperature, humidity, energy, and air quality. All four share a single Docker image; the specific sensor behaviour is selected at startup through an environment variable. Each sensor exposes a REST endpoint that returns a randomly generated reading in JSON format, as well as a health-check endpoint used by Kubernetes probes and a Prometheus-compatible metrics endpoint.

To enable accurate CPU monitoring inside containers, each sensor runs a background thread that measures per-process CPU usage and normalises it against the container's CPU limit. This means the reported CPU percentage reflects how much of the pod's allocated resources are being used, rather than the total node capacity.

For testing purposes, each sensor also exposes a stress endpoint that artificially burns CPU for a configurable duration. This allows us to simulate load and trigger the auto-scaler.

## 4. Load Balancer

The load balancer serves as the single entry point for all external traffic. It discovers sensor pods by polling the Kubernetes API in a background thread and maintains an up-to-date list of running pod IPs grouped by sensor type.

When a request arrives for a specific sensor service, the load balancer selects the next pod in round-robin order and forwards the request. This per-service routing ensures that traffic intended for one sensor type is never accidentally sent to another.

The load balancer also serves the web dashboard — a single-page application built with Vue 3 and Tailwind CSS. The dashboard refreshes every second and displays live sensor readings with colour-coded threshold indicators, the current number of pods per sensor, and per-pod CPU utilisation sourced from the scaler's status API.

Additionally, the load balancer exposes aggregation endpoints that the dashboard consumes: one for pod status, one for sensor readings, and one that proxies the scaler's internal state.

## 5. Scaler (Control Plane)

The scaler is the core of the project. It implements a custom auto-scaling controller that runs as a standalone Kubernetes pod and operates independently of the built-in Horizontal Pod Autoscaler.

### Scaling Algorithm

The scaler evaluates each sensor deployment independently on a fixed interval. Each cycle follows these steps:

First, it scrapes the Prometheus metrics endpoint on every running pod of a given deployment and computes the average CPU utilisation across all pods. Then, it feeds this average into a sliding window that smooths the value over multiple samples, preventing the scaler from reacting to momentary spikes. Once the window is full, the smoothed CPU value is compared against two thresholds.

If the smoothed CPU exceeds the upper threshold, the scaler adds one replica. If it falls below the lower threshold, it removes one replica. Values between the two thresholds fall into a hysteresis band where no action is taken. This dead zone prevents the system from oscillating between scaling up and scaling down.

After every scaling action, a cooldown period blocks further changes to the same deployment. This gives the newly added or removed pods time to start up and for the metrics to stabilise before the next decision is made.

Replica counts are bounded by configurable minimum and maximum values. Scaling is performed by patching the Kubernetes Deployment object through the API, with exponential backoff on conflict errors.

### Observability

The scaler exposes a status API that returns its internal state for each deployment — including the raw and smoothed CPU averages, per-pod CPU breakdown, the current sliding window contents, and the remaining cooldown time. The load balancer proxies this data to the dashboard, giving users real-time visibility into the scaler's decision-making process.

### RBAC

The scaler uses a dedicated Kubernetes service account with a narrowly scoped Role that grants read access to pods (for metric scraping) and read/write access to deployment scale subresources (for adjusting replicas).

## 6. Monitoring

### Prometheus

Prometheus runs as a dedicated Kubernetes Deployment (`prom/prometheus:v2.51.0`) with a ClusterIP Service on port 9090. It is configured with a 5-second global scrape and evaluation interval and a 1-hour TSDB retention window. Its configuration is stored in a ConfigMap and mounted into the container.

Pod discovery uses the Kubernetes service-discovery mechanism (`kubernetes_sd_configs` with `role: pod`). Only pods annotated with `prometheus.io/scrape: "true"` are scraped; the scrape port and path are read from the `prometheus.io/port` and `prometheus.io/path` annotations respectively. All four sensor deployments carry these annotations, so Prometheus automatically discovers new pod replicas as the scaler adds or removes them. The pod name and `app` label are propagated as metric labels to identify the source of each time series.

In addition to the pod-discovery job, a static scrape job targets `scaler-svc:8081/metrics` directly. This captures the scaler's own Prometheus metrics: `scaler_deployment_replicas`, `scaler_deployment_avg_cpu`, and `scaler_deployment_avg_ram`, one series per deployment.

Prometheus runs under a dedicated service account (`prometheus-sa`) bound to a ClusterRole that grants `get`, `list`, and `watch` on pods, endpoints, nodes, and services in all namespaces — the minimum permissions required for Kubernetes service discovery.

### Grafana

Grafana runs as a dedicated Kubernetes Deployment (`grafana/grafana:10.3.1`) with a NodePort Service on port 3000 (node port 30030). The setup script also establishes a local `kubectl port-forward` to the same port, making Grafana reachable at `http://127.0.0.1:30030` without needing direct node access. Anonymous access is enabled with Admin-level permissions and the login form is disabled, so no credentials are required.

The Prometheus data source and the dashboard are both fully provisioned via ConfigMaps, so no manual setup is needed after deployment. The pre-built "Cloud Sensors" dashboard auto-refreshes every 5 seconds and shows the last 15 minutes of data across five panels:

| Panel | Metric | Description |
| --- | --- | --- |
| CPU % per Pod | `app_cpu_percent` | Per-pod CPU utilisation as a fraction of the pod's CPU limit |
| Average CPU % per Deployment | `scaler_deployment_avg_cpu` | Smoothed average used by the scaler, with dashed reference lines at the 70% scale-up and 30% scale-down thresholds |
| RAM per Pod (MB) | `app_ram_bytes / 1024 / 1024` | Per-pod resident memory usage |
| Request Rate per Pod (req/s) | `rate(app_requests_total[30s])` | Incoming request throughput broken down by pod and HTTP status |
| Replica Count per Deployment | `scaler_deployment_replicas` | Current number of running replicas for each sensor deployment |

## 7. Kubernetes Deployment

All components are defined as standard Kubernetes resources. Each sensor type has its own Deployment and ClusterIP Service. The load balancer has a Deployment and a NodePort Service (node port 30080) for external access. The scaler has a Deployment and a ClusterIP Service for its status API on port 8081. Prometheus has a Deployment and a ClusterIP Service on port 9090. Grafana has a Deployment and a NodePort Service (node port 30030).

Resource requests and limits are set on every container to ensure fair scheduling and to make CPU measurements meaningful — the normalised CPU percentage is calculated relative to the pod's CPU limit.

Sensor pods include both readiness and liveness probes based on their health-check endpoint, ensuring Kubernetes only routes traffic to healthy pods and restarts unresponsive ones.

The load balancer and scaler share the same Kubernetes service account (`scaler-sa`), which is bound to a Role granting the necessary read access to pods and read/write access to deployments — both components need to query the Kubernetes API for pod discovery.

A single setup script creates an isolated Minikube profile, builds all three Docker images inside the cluster, applies all manifests, waits for readiness, and sets up local `kubectl port-forward` sessions for the load balancer (port 18080) and Grafana (port 30030). A corresponding teardown script cleans everything up.

## 8. Stress Testing

Two stress-testing scripts are included to validate the scaling behaviour.

The burn test sends long-running CPU-intensive requests through the load balancer. Each request occupies one pod for several seconds, so each concurrent worker saturates exactly one pod. This is useful for testing targeted scale-up: starting with one worker triggers a single pod to hit full CPU usage, the scaler adds a replica, and adding a second worker saturates the new pod as well.

The flood test sends a high volume of lightweight requests as fast as possible. Because each request completes in milliseconds, the round-robin distributes them evenly across all pods, causing all replicas to experience a roughly equal CPU increase. This tests the system's behaviour under distributed load.

Both scripts can target any sensor type and accept configurable duration and concurrency parameters.

## 9. Tech Stack

The project is built entirely in Python using the FastAPI web framework with Uvicorn as the ASGI server. Sensor metrics are exposed in Prometheus format using the official Prometheus client library, and CPU measurement relies on psutil with cgroup-aware normalisation. The load balancer uses httpx for proxying requests, while the scaler uses aiohttp for asynchronous metric scraping. The frontend dashboard is a single HTML file using Vue 3 and Tailwind CSS. Metrics collection and storage are handled by Prometheus (v2.51.0), and Grafana (v10.3.1) provides pre-provisioned dashboards with no login required. All services are containerised with Docker and orchestrated on Kubernetes via Minikube.

## Appendix: Project Structure

```text
microservice/           Sensor pods (shared Docker image)
  base_app.py             Shared FastAPI app factory, metrics, stress endpoint
  sensors/                temperature, humidity, energy, air_quality modules
  test_sensors.py         Local integration tests

lb/                     Load balancer + dashboard
  main.py                 Entry point
  round_robin.py          Round-robin logic and API routes
  pod_sync.py             Kubernetes pod discovery thread
  static/index.html       Vue 3 dashboard

scaler/                 Custom auto-scaler
  main.py                 Entry point and status API server
  scaler.py               Threshold evaluator and manager
  monitor.py              Async Prometheus scraper
  k8s_client.py           Kubernetes API wrapper
  metrics_window.py       Sliding window for smoothing

k8s/                    Kubernetes manifests
  rbac.yaml               Scaler + LB service account and Role
  prometheus-rbac.yaml    Prometheus service account and ClusterRole
  sensor-*.yaml           Sensor Deployments and ClusterIP Services
  lb-deployment.yaml      Load balancer Deployment and NodePort Service
  scaler-deployment.yaml  Scaler Deployment and ClusterIP Service
  prometheus-deployment.yaml  Prometheus ConfigMap, Deployment, and ClusterIP Service
  grafana-deployment.yaml     Grafana ConfigMaps, Deployment, and NodePort Service

scripts/                Setup, teardown, and stress-test scripts
  start-minikube.sh       Create cluster, build images, deploy, port-forward
  stop-minikube.sh        Tear down cluster and stop port-forwards
  stess-test.sh           CPU burn stress test
  stress-test-flood.sh    High-volume flood stress test
```
