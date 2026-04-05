#!/usr/bin/env bash
set -euo pipefail

PROFILE="${MINIKUBE_PROFILE:-cloud-lb}"
CPUS="${MINIKUBE_CPUS:-4}"
MEMORY="${MINIKUBE_MEMORY:-4096}"
NAMESPACE="${K8S_NAMESPACE:-default}"
LOCAL_PORT="${LB_LOCAL_PORT:-18080}"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUNTIME_DIR="${TMPDIR:-/tmp}"
PID_FILE="$RUNTIME_DIR/${PROFILE}-lb-port-forward.pid"
LOG_FILE="$RUNTIME_DIR/${PROFILE}-lb-port-forward.log"

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

echo "[1/9] Recreate isolated Minikube profile: $PROFILE"
minikube delete -p "$PROFILE" >/dev/null 2>&1 || true
minikube start -p "$PROFILE" --driver=docker --cpus="$CPUS" --memory="$MEMORY"

echo "[2/9] Build sensor image inside Minikube"
minikube image build -p "$PROFILE" -t house-sensor:latest "$ROOT_DIR/microservice"

echo "[3/9] Build load balancer image inside Minikube"
minikube image build -p "$PROFILE" -t house-lb:latest "$ROOT_DIR/lb"

echo "[4/9] Build scaler image inside Minikube"
minikube image build -p "$PROFILE" -t house-scaler:latest "$ROOT_DIR/scaler"

echo "[5/9] Apply RBAC and manifests"
kubectl --context "$PROFILE" -n "$NAMESPACE" apply -f "$ROOT_DIR/k8s/rbac.yaml"
kubectl --context "$PROFILE" -n "$NAMESPACE" apply \
  -f "$ROOT_DIR/k8s/sensor-temperature.yaml" \
  -f "$ROOT_DIR/k8s/sensor-humidity.yaml" \
  -f "$ROOT_DIR/k8s/sensor-energy.yaml" \
  -f "$ROOT_DIR/k8s/sensor-air-quality.yaml" \
  -f "$ROOT_DIR/k8s/lb-deployment.yaml" \
  -f "$ROOT_DIR/k8s/scaler-deployment.yaml"

echo "[6/9] Wait for deployments"
kubectl --context "$PROFILE" -n "$NAMESPACE" wait \
  --for=condition=Available \
  --timeout=240s \
  deployment/sensor-temperature \
  deployment/sensor-humidity \
  deployment/sensor-energy \
  deployment/sensor-air-quality \
  deployment/load-balancer \
  deployment/scaler

echo "[7/9] Restart local port-forward"
if [ -f "$PID_FILE" ]; then
  old_pid="$(cat "$PID_FILE" || true)"
  if [ -n "$old_pid" ] && kill -0 "$old_pid" >/dev/null 2>&1; then
    kill "$old_pid" >/dev/null 2>&1 || true
    sleep 1
  fi
fi

# Fallback cleanup for stale kubectl port-forward processes
pkill -f "kubectl --context $PROFILE.*port-forward service/load-balancer" >/dev/null 2>&1 || true

nohup kubectl --context "$PROFILE" -n "$NAMESPACE" port-forward service/load-balancer "$LOCAL_PORT:8080" >"$LOG_FILE" 2>&1 &
echo $! >"$PID_FILE"
sleep 2

if ! kill -0 "$(cat "$PID_FILE")" >/dev/null 2>&1; then
  echo "Port-forward failed, see log: $LOG_FILE" >&2
  exit 1
fi

echo "[8/9] Verify API is reachable"
curl -fsS "http://127.0.0.1:$LOCAL_PORT/api/status" >/dev/null

echo "[9/9] Ready"
echo "Dashboard: http://127.0.0.1:$LOCAL_PORT/dashboard"
echo "Scaler logs: kubectl --context $PROFILE logs -f deployment/scaler"
