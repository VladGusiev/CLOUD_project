#!/usr/bin/env bash
set -euo pipefail

PROFILE="${MINIKUBE_PROFILE:-cloud-lb}"
CPUS="${MINIKUBE_CPUS:-4}"
MEMORY="${MINIKUBE_MEMORY:-4096}"
NAMESPACE="${K8S_NAMESPACE:-default}"
LOCAL_PORT="${LB_LOCAL_PORT:-18080}"
GRAFANA_LOCAL_PORT="${GRAFANA_LOCAL_PORT:-30030}"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUNTIME_DIR="${TMPDIR:-/tmp}"
PID_FILE="$RUNTIME_DIR/${PROFILE}-lb-port-forward.pid"
LOG_FILE="$RUNTIME_DIR/${PROFILE}-lb-port-forward.log"
GRAFANA_PID_FILE="$RUNTIME_DIR/${PROFILE}-grafana-port-forward.pid"
GRAFANA_LOG_FILE="$RUNTIME_DIR/${PROFILE}-grafana-port-forward.log"

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing required command: $1" >&2
    exit 1
  fi
}

for cmd in minikube kubectl docker curl; do
  require_cmd "$cmd"
done

PREV_CONTEXT="$(kubectl config current-context 2>/dev/null || true)"
cleanup_context() {
  if [ -n "$PREV_CONTEXT" ]; then
    kubectl config use-context "$PREV_CONTEXT" >/dev/null 2>&1 || true
  fi
}
trap cleanup_context EXIT

echo "[1/11] Recreate isolated Minikube profile: $PROFILE"
minikube delete -p "$PROFILE" >/dev/null 2>&1 || true
minikube start -p "$PROFILE" --driver=docker --cpus="$CPUS" --memory="$MEMORY"

echo "[2/11] Build sensor image inside Minikube"
minikube image build -p "$PROFILE" -t house-sensor:latest "$ROOT_DIR/microservice"

echo "[3/11] Build load balancer image inside Minikube"
minikube image build -p "$PROFILE" -t house-lb:latest "$ROOT_DIR/lb"

echo "[4/11] Build scaler image inside Minikube"
minikube image build -p "$PROFILE" -t house-scaler:latest "$ROOT_DIR/scaler"

echo "[5/11] Apply RBAC and manifests"
kubectl --context "$PROFILE" -n "$NAMESPACE" apply -f "$ROOT_DIR/k8s/rbac.yaml"
kubectl --context "$PROFILE" -n "$NAMESPACE" apply \
  -f "$ROOT_DIR/k8s/sensor-temperature.yaml" \
  -f "$ROOT_DIR/k8s/sensor-humidity.yaml" \
  -f "$ROOT_DIR/k8s/sensor-energy.yaml" \
  -f "$ROOT_DIR/k8s/sensor-air-quality.yaml" \
  -f "$ROOT_DIR/k8s/lb-deployment.yaml" \
  -f "$ROOT_DIR/k8s/scaler-deployment.yaml"

echo "[6/11] Apply Prometheus and Grafana"
kubectl --context "$PROFILE" -n "$NAMESPACE" apply -f "$ROOT_DIR/k8s/prometheus-rbac.yaml"
kubectl --context "$PROFILE" -n "$NAMESPACE" apply \
  -f "$ROOT_DIR/k8s/prometheus-deployment.yaml" \
  -f "$ROOT_DIR/k8s/grafana-deployment.yaml"

echo "[7/11] Wait for sensor/LB/scaler deployments"
kubectl --context "$PROFILE" -n "$NAMESPACE" wait \
  --for=condition=Available \
  --timeout=240s \
  deployment/sensor-temperature \
  deployment/sensor-humidity \
  deployment/sensor-energy \
  deployment/sensor-air-quality \
  deployment/load-balancer \
  deployment/scaler

echo "[8/11] Wait for Prometheus and Grafana"
kubectl --context "$PROFILE" -n "$NAMESPACE" wait \
  --for=condition=Available \
  --timeout=180s \
  deployment/prometheus \
  deployment/grafana

echo "[9/11] Restart local port-forwards"
# -- Load balancer --
if [ -f "$PID_FILE" ]; then
  old_pid="$(cat "$PID_FILE" || true)"
  if [ -n "$old_pid" ] && kill -0 "$old_pid" >/dev/null 2>&1; then
    kill "$old_pid" >/dev/null 2>&1 || true
    sleep 1
  fi
fi
pkill -f "kubectl --context $PROFILE.*port-forward service/load-balancer" >/dev/null 2>&1 || true
nohup kubectl --context "$PROFILE" -n "$NAMESPACE" port-forward service/load-balancer "$LOCAL_PORT:8080" >"$LOG_FILE" 2>&1 &
echo $! >"$PID_FILE"

# -- Grafana --
if [ -f "$GRAFANA_PID_FILE" ]; then
  old_pid="$(cat "$GRAFANA_PID_FILE" || true)"
  if [ -n "$old_pid" ] && kill -0 "$old_pid" >/dev/null 2>&1; then
    kill "$old_pid" >/dev/null 2>&1 || true
    sleep 1
  fi
fi
pkill -f "kubectl --context $PROFILE.*port-forward service/grafana-svc" >/dev/null 2>&1 || true
nohup kubectl --context "$PROFILE" -n "$NAMESPACE" port-forward service/grafana-svc "$GRAFANA_LOCAL_PORT:3000" >"$GRAFANA_LOG_FILE" 2>&1 &
echo $! >"$GRAFANA_PID_FILE"

sleep 2
if ! kill -0 "$(cat "$PID_FILE")" >/dev/null 2>&1; then
  echo "LB port-forward failed, see log: $LOG_FILE" >&2
  exit 1
fi
if ! kill -0 "$(cat "$GRAFANA_PID_FILE")" >/dev/null 2>&1; then
  echo "Grafana port-forward failed, see log: $GRAFANA_LOG_FILE" >&2
  exit 1
fi

echo "[10/11] Verify API is reachable"
curl -fsS "http://127.0.0.1:$LOCAL_PORT/api/status" >/dev/null

echo "[11/11] Ready"
echo "Demo dashboard : http://127.0.0.1:$LOCAL_PORT/dashboard"
echo "Grafana        : http://127.0.0.1:$GRAFANA_LOCAL_PORT  (no login required)"
echo "Prometheus     : kubectl --context $PROFILE -n $NAMESPACE port-forward svc/prometheus-svc 9090:9090"
echo "Scaler logs    : kubectl --context $PROFILE logs -f deployment/scaler"
