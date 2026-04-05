#!/usr/bin/env bash
# stress-test-flood.sh — High-frequency lightweight requests to spike CPU evenly.
#
# Unlike the burn-based stress test, this sends many fast requests per second
# (e.g. /sensor/reading). Because each request completes quickly, the LB
# round-robin distributes them evenly across ALL pods — spiking CPU on every
# pod roughly equally.
#
# Usage:
#   ./scripts/stress-test-flood.sh              # defaults: 60s, 8 workers, sensor-temperature
#   ./scripts/stress-test-flood.sh 120 16       # 120s, 16 workers
#   STRESS_TARGET=sensor-energy ./scripts/stress-test-flood.sh
set -euo pipefail

LB_URL="${LB_URL:-http://127.0.0.1:18080}"
TARGET_SENSOR="${STRESS_TARGET:-sensor-temperature}"
DURATION="${1:-60}"
WORKERS="${2:-8}"

echo "=== Flood Stress Test ==="
echo "Target   : $TARGET_SENSOR (via LB: $LB_URL/$TARGET_SENSOR/sensor/reading)"
echo "Duration : ${DURATION}s"
echo "Workers  : $WORKERS (each sends requests as fast as possible)"
echo ""

flood_worker() {
  local deadline=$1
  while [ "$(date +%s)" -lt "$deadline" ]; do
    curl -s -m 2 "${LB_URL}/${TARGET_SENSOR}/sensor/reading" >/dev/null 2>&1 || true
  done
}

DEADLINE=$(( $(date +%s) + DURATION ))
PIDS=()

echo "[$(date +%H:%M:%S)] Starting flood on $TARGET_SENSOR..."

for i in $(seq 1 "$WORKERS"); do
  flood_worker "$DEADLINE" &
  PIDS+=($!)
done

echo "[$(date +%H:%M:%S)] ${#PIDS[@]} workers flooding. Press Ctrl+C to stop early."

cleanup() {
  echo ""
  echo "Stopping workers..."
  kill "${PIDS[@]}" 2>/dev/null || true
  wait "${PIDS[@]}" 2>/dev/null || true
  echo "Done."
}
trap cleanup EXIT INT TERM

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
echo "[$(date +%H:%M:%S)] Flood test complete."
echo "Expected: all $TARGET_SENSOR pods spiked CPU roughly equally."
