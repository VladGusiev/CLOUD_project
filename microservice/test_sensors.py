import json
import subprocess
import sys
import time
import urllib.request
import urllib.error

VENV_UVICORN = ".venv/bin/uvicorn"

SENSORS = [
    {"type": "temperature", "port": 18080, "module": "sensors.temperature"},
    {"type": "humidity",    "port": 18081, "module": "sensors.humidity"},
    {"type": "energy",      "port": 18082, "module": "sensors.energy"},
    {"type": "air_quality", "port": 18083, "module": "sensors.air_quality"},
]

def get(url: str, timeout: int = 5) -> dict | str:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            body = r.read().decode()
            try:
                return json.loads(body)
            except json.JSONDecodeError:
                return body
    except Exception as e:
        return {"ERROR": str(e)}

def wait_for_port(port: int, retries: int = 15, delay: float = 0.5) -> bool:
    for _ in range(retries):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1)
            return True
        except Exception:
            time.sleep(delay)
    return False

def run_test(sensor: dict, proc: subprocess.Popen) -> bool:
    t = sensor["type"]
    p = sensor["port"]
    base = f"http://127.0.0.1:{p}"
    ok = True

    health = get(f"{base}/health")
    health_ok = health == {"status": "ok"}
    print(f"  /health        {'OK' if health_ok else 'FAIL'}  {health}")
    ok = ok and health_ok

    reading = get(f"{base}/sensor/reading")
    reading_ok = isinstance(reading, dict) and "type" in reading
    print(f"  /sensor/reading{'OK' if reading_ok else 'FAIL'}  {reading}")
    ok = ok and reading_ok

    stress_url = f"{base}/stress?cpu_seconds=1&ram_mb=8"
    req = urllib.request.Request(stress_url, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            stress = json.loads(r.read())
        stress_ok = stress.get("status") == "done"
    except Exception as e:
        stress = {"ERROR": str(e)}
        stress_ok = False
    print(f"  /stress        {'OK' if stress_ok else 'FAIL'}  {stress}")
    ok = ok and stress_ok

    metrics_raw = get(f"{base}/metrics")
    metrics_ok = isinstance(metrics_raw, str) and "app_cpu_percent" in metrics_raw
    metric_lines = [l for l in metrics_raw.splitlines()
                    if l.startswith(("app_cpu", "app_ram", f"sensor_{t}"))]
    print(f"  /metrics       {'OK' if metrics_ok else 'FAIL'}")
    for line in metric_lines:
        print(f"    {line}")
    ok = ok and metrics_ok

    return ok

def main():
    procs = []
    all_ok = True
    try:
        for s in SENSORS:
            import os
            env = {**os.environ, "SENSOR_TYPE": s["type"]}
            proc = subprocess.Popen(
                [VENV_UVICORN, s["module"] + ":app",
                 "--host", "127.0.0.1", "--port", str(s["port"]),
                 "--log-level", "warning"],
                env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            procs.append((s, proc))

        print("Waiting for servers...")
        for s, _ in procs:
            ready = wait_for_port(s["port"])
            if not ready: all_ok = False

        for s, proc in procs:
            print(f"Testing {s['type']} (port {s['port']})")
            sensor_ok = run_test(s, proc)
            all_ok = all_ok and sensor_ok
            print(f"Result: {'PASS' if sensor_ok else 'FAIL'}\n")

    finally:
        for _, proc in procs:
            proc.terminate()

    if all_ok:
        print("ALL TESTS PASSED")
    else:
        print("SOME TESTS FAILED")
        sys.exit(1)

if __name__ == "__main__":
    main()
