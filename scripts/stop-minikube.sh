#!/usr/bin/env bash
set -euo pipefail

PROFILE="${MINIKUBE_PROFILE:-cloud-lb}"
RUNTIME_DIR="${TMPDIR:-/tmp}"
PID_FILE="$RUNTIME_DIR/${PROFILE}-lb-port-forward.pid"
LOG_FILE="$RUNTIME_DIR/${PROFILE}-lb-port-forward.log"

echo "[1/4] Stop port-forward if running"
if [ -f "$PID_FILE" ]; then
  pid="$(cat "$PID_FILE" || true)"
  if [ -n "$pid" ] && kill -0 "$pid" >/dev/null 2>&1; then
    kill "$pid" >/dev/null 2>&1 || true
  fi
  rm -f "$PID_FILE"
fi

# Fallback cleanup for stale kubectl port-forward processes
pkill -f "kubectl --context $PROFILE.*port-forward service/load-balancer" >/dev/null 2>&1 || true

echo "[2/4] Delete isolated Minikube profile"
minikube delete -p "$PROFILE" >/dev/null 2>&1 || true

echo "[3/4] Remove local temp files"
rm -f "$LOG_FILE"

echo "[4/4] Cleanup complete"
echo "Profile '$PROFILE' removed. Other Minikube profiles are untouched."
