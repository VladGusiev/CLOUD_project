#!/usr/bin/env bash
# stress-test.sh — Concentrated load on one sensor to trigger scaling.
#
# Routes through the LB using per-service routing: /{sensor-label}/stress
# so all requests hit only the targeted sensor's pods.
#
# Usage:
#   ./scripts/stress-test.sh              # defaults: 120s on sensor-temperature
#   ./scripts/stress-test.sh 180 5        # 180s duration, 5 workers
#   STRESS_TARGET=sensor-energy ./scripts/stress-test.sh  # target different sensor
set -euo pipefail

LB_URL="${LB_URL:-http://127.0.0.1:18080}"
TARGET_SENSOR="${STRESS_TARGET:-sensor-temperature}"
DURATION="${1:-120}"
WORKERS="${2:-4}"
CPU_SECONDS="6"
RAM_MB="32"

echo "=== Stress Test ==="
echo "Target   : $TARGET_SENSOR (via LB: $LB_URL/$TARGET_SENSOR/stress)"
echo "Duration : ${DURATION}s"
echo "Workers  : $WORKERS"
echo "Payload  : cpu=${CPU_SECONDS}s, ram=${RAM_MB}MB per request"
echo ""
echo "Monitor in other terminals:"
echo "  kubectl get pods -w"
echo "  kubectl --context cloud-lb logs -f deployment/scaler"
echo ""

# Worker: loops sending /stress via LB per-service route
stress_worker() {
  local deadline=$1
  while [ "$(date +%s)" -lt "$deadline" ]; do
    curl -s -m 9 -X POST "${LB_URL}/${TARGET_SENSOR}/stress?cpu_seconds=${CPU_SECONDS}&ram_mb=${RAM_MB}" >/dev/null 2>&1 || true
    sleep 0.5
  done
}

DEADLINE=$(( $(date +%s) + DURATION ))
PIDS=()

echo "[$(date +%H:%M:%S)] Starting load on $TARGET_SENSOR..."

for i in $(seq 1 "$WORKERS"); do
  stress_worker "$DEADLINE" &
  PIDS+=($!)
done

echo "[$(date +%H:%M:%S)] ${#PIDS[@]} workers running. Press Ctrl+C to stop early."

cleanup() {
  echo ""
  echo "Stopping workers..."
  kill "${PIDS[@]}" 2>/dev/null || true
  wait "${PIDS[@]}" 2>/dev/null || true
  echo "Done."
}
trap cleanup EXIT INT TERM

# Progress indicator
ELAPSED=0
while [ "$(date +%s)" -lt "$DEADLINE" ]; do
  sleep 10
  ELAPSED=$(( ELAPSED + 10 ))
  REMAINING=$(( DEADLINE - $(date +%s) ))
  [ "$REMAINING" -lt 0 ] && REMAINING=0
  echo "[$(date +%H:%M:%S)] ${ELAPSED}s elapsed, ${REMAINING}s remaining..."
done

wait "${PIDS[@]}" 2>/dev/null || true
trap - EXIT INT TERM
echo ""
echo "[$(date +%H:%M:%S)] Stress test complete."
echo "Expected: $TARGET_SENSOR scaled up, other sensors stayed at ~1% CPU."
echo "Watch for scale-down after load stops + 45s cooldown."