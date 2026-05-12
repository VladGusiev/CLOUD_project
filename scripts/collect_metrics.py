#!/usr/bin/env python3

import json
import signal
import sys
import time
import urllib.request
from datetime import datetime, timezone

LB_URL = "http://127.0.0.1:18080"
INTERVAL = int(sys.argv[2]) if len(sys.argv) > 2 else 5
output_path = sys.argv[1] if len(sys.argv) > 1 else "results/metrics.json"
samples = []
running = True


def stop(signum, frame):
    global running
    running = False


signal.signal(signal.SIGINT, stop)
signal.signal(signal.SIGTERM, stop)


def fetch_scaler():
    url = f"{LB_URL}/api/scaler-status"
    with urllib.request.urlopen(url, timeout=4) as resp:
        return json.loads(resp.read())


print(f"[collector] writing → {output_path}, interval={INTERVAL}s", flush=True)

while running:
    ts = datetime.now(timezone.utc).isoformat()
    try:
        data = fetch_scaler()
        for sensor, info in data.items():
            samples.append({
                "ts": ts,
                "sensor": sensor,
                "replicas": info.get("replicas", 0),
                "avg_cpu": info.get("avg_cpu", 0.0),
                "smoothed_cpu": info.get("smoothed_cpu", 0.0),
                "cooldown_remaining": info.get("cooldown_remaining", 0.0),
                "per_pod": info.get("per_pod", []),
            })
        print(f"[collector] {ts}  samples={len(samples)}", flush=True)
    except Exception as exc:
        print(f"[collector] WARN {ts}: {exc}", flush=True)

    for _ in range(INTERVAL * 10):
        if not running:
            break
        time.sleep(0.1)

with open(output_path, "w") as f:
    json.dump(samples, f, indent=2)

print(f"[collector] saved {len(samples)} samples → {output_path}", flush=True)
