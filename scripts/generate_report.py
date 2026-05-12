#!/usr/bin/env python3

import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from tabulate import tabulate


# ── args ────────────────────────────────────────────────────────────────────
metrics_path = sys.argv[1] if len(sys.argv) > 1 else "results/metrics.json"
out_dir      = sys.argv[2] if len(sys.argv) > 2 else "results"
test_label   = sys.argv[3] if len(sys.argv) > 3 else "Stress Test"

os.makedirs(out_dir, exist_ok=True)

with open(metrics_path) as f:
    samples = json.load(f)

if not samples:
    print("No samples found — nothing to report.")
    sys.exit(0)

# ── organise by sensor ───────────────────────────────────────────────────────
sensors_data: dict[str, list] = defaultdict(list)
for s in samples:
    sensors_data[s["sensor"]].append(s)

sensors = sorted(sensors_data.keys())

COLORS = {
    "sensor-temperature": "#e74c3c",
    "sensor-humidity":    "#3498db",
    "sensor-energy":      "#f39c12",
    "sensor-air-quality": "#2ecc71",
}

def parse_ts(ts: str) -> datetime:
    return datetime.fromisoformat(ts)

def times_and_values(rows, key):
    xs = [parse_ts(r["ts"]) for r in rows]
    ys = [r[key] for r in rows]
    return xs, ys

#Figure 1: CPU % over time
fig, axes = plt.subplots(len(sensors), 1, figsize=(12, 3 * len(sensors)), sharex=True)
if len(sensors) == 1:
    axes = [axes]

fig.suptitle(f"{test_label} — CPU % over time (smoothed)", fontsize=14, fontweight="bold")

for ax, sensor in zip(axes, sensors):
    rows = sensors_data[sensor]
    xs, raw_cpu   = times_and_values(rows, "avg_cpu")
    _,  smth_cpu  = times_and_values(rows, "smoothed_cpu")
    color = COLORS.get(sensor, "#7f8c8d")

    ax.fill_between(xs, raw_cpu, alpha=0.25, color=color)
    ax.plot(xs, raw_cpu,  color=color, alpha=0.6, linewidth=1, label="avg CPU %")
    ax.plot(xs, smth_cpu, color=color, linewidth=2,  label="smoothed CPU %")

    ax.axhline(70, color="red",    linestyle="--", linewidth=0.8, label="scale-up  (70 %)")
    ax.axhline(30, color="orange", linestyle="--", linewidth=0.8, label="scale-down (30 %)")

    ax.set_ylabel("CPU %")
    ax.set_ylim(0, 110)
    ax.set_title(sensor, fontsize=10)
    ax.legend(fontsize=7, loc="upper right")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M:%S"))
    ax.grid(True, alpha=0.3)

plt.xticks(rotation=30, ha="right")
plt.tight_layout()
cpu_png = os.path.join(out_dir, "cpu.png")
fig.savefig(cpu_png, dpi=150, bbox_inches="tight")
plt.close()
print(f"[report] saved {cpu_png}")

# Figure 2: replica count over time
fig, axes = plt.subplots(len(sensors), 1, figsize=(12, 3 * len(sensors)), sharex=True)
if len(sensors) == 1:
    axes = [axes]

fig.suptitle(f"{test_label} — Replica count over time", fontsize=14, fontweight="bold")

for ax, sensor in zip(axes, sensors):
    rows = sensors_data[sensor]
    xs, replicas = times_and_values(rows, "replicas")
    color = COLORS.get(sensor, "#7f8c8d")

    ax.step(xs, replicas, where="post", color=color, linewidth=2)
    ax.fill_between(xs, replicas, step="post", alpha=0.15, color=color)

    ax.set_ylabel("Replicas")
    ax.set_ylim(0, 6)
    ax.set_yticks(range(0, 6))
    ax.set_title(sensor, fontsize=10)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M:%S"))
    ax.grid(True, alpha=0.3)

plt.xticks(rotation=30, ha="right")
plt.tight_layout()
rep_png = os.path.join(out_dir, "replicas.png")
fig.savefig(rep_png, dpi=150, bbox_inches="tight")
plt.close()
print(f"[report] saved {rep_png}")

# Figure 3: combined overview
fig, (ax_cpu, ax_rep) = plt.subplots(2, 1, figsize=(14, 8), sharex=True)
fig.suptitle(f"{test_label} — Overview", fontsize=14, fontweight="bold")

for sensor in sensors:
    rows  = sensors_data[sensor]
    xs, smth_cpu = times_and_values(rows, "smoothed_cpu")
    _,  replicas = times_and_values(rows, "replicas")
    color = COLORS.get(sensor, "#7f8c8d")
    label = sensor.replace("sensor-", "")
    ax_cpu.plot(xs, smth_cpu, color=color, linewidth=2, label=label)
    ax_rep.step(xs, replicas, where="post", color=color, linewidth=2, label=label)

ax_cpu.axhline(70, color="red",    linestyle="--", linewidth=0.8, alpha=0.7)
ax_cpu.axhline(30, color="orange", linestyle="--", linewidth=0.8, alpha=0.7)
ax_cpu.set_ylabel("Smoothed CPU %")
ax_cpu.set_ylim(0, 110)
ax_cpu.legend(fontsize=9)
ax_cpu.grid(True, alpha=0.3)
ax_cpu.set_title("CPU utilisation")

ax_rep.set_ylabel("Replicas")
ax_rep.set_ylim(0, 6)
ax_rep.set_yticks(range(0, 6))
ax_rep.legend(fontsize=9)
ax_rep.grid(True, alpha=0.3)
ax_rep.set_title("Replica count")
ax_rep.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M:%S"))

plt.xticks(rotation=30, ha="right")
plt.tight_layout()
overview_png = os.path.join(out_dir, "overview.png")
fig.savefig(overview_png, dpi=150, bbox_inches="tight")
plt.close()
print(f"[report] saved {overview_png}")

# Summary table
summary_rows = []
for sensor in sensors:
    rows = sensors_data[sensor]
    cpus     = [r["avg_cpu"] for r in rows]
    smoothed = [r["smoothed_cpu"] for r in rows]
    replicas = [r["replicas"] for r in rows]
    summary_rows.append([
        sensor.replace("sensor-", ""),
        len(rows),
        f"{min(cpus):.1f}",
        f"{max(cpus):.1f}",
        f"{sum(cpus)/len(cpus):.1f}",
        f"{max(smoothed):.1f}",
        min(replicas),
        max(replicas),
    ])

summary_headers = [
    "Sensor", "Samples",
    "CPU min %", "CPU max %", "CPU avg %", "CPU smooth max %",
    "Replicas min", "Replicas max",
]

# Scale-event table
scale_events = []
for sensor in sensors:
    rows = sensors_data[sensor]
    for i in range(1, len(rows)):
        prev, curr = rows[i-1], rows[i]
        if curr["replicas"] != prev["replicas"]:
            direction = "↑ scale-up" if curr["replicas"] > prev["replicas"] else "↓ scale-down"
            scale_events.append([
                parse_ts(curr["ts"]).strftime("%H:%M:%S"),
                sensor.replace("sensor-", ""),
                prev["replicas"],
                curr["replicas"],
                direction,
                f"{curr['smoothed_cpu']:.1f}",
            ])

scale_headers = ["Time", "Sensor", "Old replicas", "New replicas", "Event", "Smoothed CPU %"]

# Time-series sample table (every 5th row to keep it readable)
ts_rows = []
for s in samples[::5]:
    ts_rows.append([
        parse_ts(s["ts"]).strftime("%H:%M:%S"),
        s["sensor"].replace("sensor-", ""),
        s["replicas"],
        f"{s['avg_cpu']:.1f}",
        f"{s['smoothed_cpu']:.1f}",
    ])
ts_headers = ["Time", "Sensor", "Replicas", "Avg CPU %", "Smoothed CPU %"]




start_ts = parse_ts(samples[0]["ts"]).strftime("%Y-%m-%d %H:%M:%S UTC")
end_ts   = parse_ts(samples[-1]["ts"]).strftime("%Y-%m-%d %H:%M:%S UTC")
duration = (parse_ts(samples[-1]["ts"]) - parse_ts(samples[0]["ts"])).seconds

report_md = f"""# {test_label} — Metrics Report

**Period:** {start_ts} → {end_ts} ({duration}s)
**Samples collected:** {len(samples)}
**Sensors monitored:** {len(sensors)}

---

## Summary
{tabulate(summary_rows, headers=summary_headers, tablefmt="github")}

---
## Scale Events
"""
if scale_events:
    report_md += tabulate(scale_events, headers=scale_headers, tablefmt="github")
else:
    report_md += "_No scaling events recorded during this test._"

report_md += f"""
---

## Charts

### CPU utilisation over time
![CPU over time](cpu.png)

### Replica count over time
![Replicas over time](replicas.png)

### Overview (all sensors)
![Overview](overview.png)

---

## Raw samples (every 5th):
{tabulate(ts_rows, headers=ts_headers, tablefmt="github")}
"""

report_path = os.path.join(out_dir, "report.md")
with open(report_path, "w") as f:
    f.write(report_md)

print(f"[report] saved {report_path}")
print()
print("Summary:")
print(tabulate(summary_rows, headers=summary_headers, tablefmt="simple"))
if scale_events:
    print()
    print("Scale Events:")
    print(tabulate(scale_events, headers=scale_headers, tablefmt="simple"))
