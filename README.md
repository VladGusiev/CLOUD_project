# Smart House — Dynamic Microservice Scaling on Kubernetes

## Start

```bash
./scripts/start-minikube.sh
```

Builds all images, applies K8s manifests, and waits for pods to be ready.
Dashboard available at <http://127.0.0.1:18080/dashboard> once complete.

## Stop

```bash
./scripts/stop-minikube.sh
```

Tears down port-forwards and deletes the Minikube profile.

## Other Scripts

| Script | Description |
| ------ | ----------- |
| `scripts/stess-test.sh [duration_s] [workers]` | CPU burn stress test — saturates one pod per worker |
| `scripts/stress-test-flood.sh [duration_s] [workers]` | High-frequency flood test — distributes load evenly across pods |
| `scripts/run-benchmark.sh` | Runs a benchmark against the cluster |
| `scripts/collect_metrics.py` | Collects metrics from the running cluster |
| `scripts/generate_report.py` | Generates a report from collected metrics |
