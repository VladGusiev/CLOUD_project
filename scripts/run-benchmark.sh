#!/usr/bin/env bash

# Usage:
#   ./scripts/run-benchmark.sh [burn|flood] [duration_s] [workers]
# Examples:
#   ./scripts/run-benchmark.sh burn 120 4
#   ./scripts/run-benchmark.sh flood 60 8
#   STRESS_TARGET=sensor-energy ./scripts/run-benchmark.sh burn 90 3
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

TEST_TYPE="${1:-burn}"
DURATION="${2:-120}"
WORKERS="${3:-4}"
TARGET_SENSOR="${STRESS_TARGET:-sensor-temperature}"
COLLECT_INTERVAL=5

RUN_ID="$(date +%Y-%m-%d_%H-%M-%S)"
OUT_DIR="$ROOT_DIR/results/$RUN_ID"
METRICS_FILE="$OUT_DIR/metrics.json"
mkdir -p "$OUT_DIR"

case "$TEST_TYPE" in
  burn)  STRESS_SCRIPT="$SCRIPT_DIR/stess-test.sh"       ; LABEL="Burn Stress Test"  ;;
  flood) STRESS_SCRIPT="$SCRIPT_DIR/stress-test-flood.sh" ; LABEL="Flood Stress Test" ;;
  *) echo "Unknown test type: $TEST_TYPE (use burn or flood)" >&2 ; exit 1 ;;
esac

echo "[            CLOUD  Benchmark Runner            ]"
printf "[  Type     : %-40s]\n" "$TEST_TYPE ($LABEL)"
printf "[  Target   : %-40s]\n" "$TARGET_SENSOR"
printf "[  Duration : %-40s]\n" "${DURATION}s"
printf "[  Workers  : %-40s]\n" "$WORKERS"
printf "[  Output   : %-40s]\n" "results/$RUN_ID"
echo ""

#Start metrics collector in background
echo "[1/4] Starting metrics collector (interval=${COLLECT_INTERVAL}s)..."
python3 "$SCRIPT_DIR/collect_metrics.py" "$METRICS_FILE" "$COLLECT_INTERVAL" &
COLLECTOR_PID=$!

cleanup() {
  echo ""
  echo "[cleanup] Stopping metrics collector (PID $COLLECTOR_PID)..."
  kill "$COLLECTOR_PID" 2>/dev/null || true
  wait "$COLLECTOR_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM
sleep 2

# Run the stress test
echo "[2/4] Running $LABEL: ${DURATION}s, ${WORKERS} workers on $TARGET_SENSOR..."
echo ""
STRESS_TARGET="$TARGET_SENSOR" bash "$STRESS_SCRIPT" "$DURATION" "$WORKERS" || true

# Wait for cooldown so we capture scale-down
COOLDOWN=50
echo ""
echo "[3/4] Waiting ${COOLDOWN}s for scale-down cooldown.."
for i in $(seq 1 "$COOLDOWN"); do
  sleep 1
  if (( i % 10 == 0 )); then
    echo "      ...${i}s / ${COOLDOWN}s"
  fi
done

# Stop collector
trap - EXIT INT TERM
echo "[4/4] Stopping collector and generating report.."
kill "$COLLECTOR_PID" 2>/dev/null || true
wait "$COLLECTOR_PID" 2>/dev/null || true

#Generate report
python3 "$SCRIPT_DIR/generate_report.py" "$METRICS_FILE" "$OUT_DIR" "$LABEL ($TARGET_SENSOR, ${DURATION}s, ${WORKERS}w)"

echo ""
echo "  Results saved to: results/$RUN_ID/"
echo "    metrics.json    - raw data"
echo "    report.md       - markdown tables + chart references"
echo "    cpu.png         - CPU % over time"
echo "    replicas.png    - replica count over time"
echo "    overview.png    - combined overview"
