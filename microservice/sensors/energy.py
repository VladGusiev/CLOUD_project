import math
import random
from prometheus_client import Gauge
from base_app import create_app

sensor_energy_kwh = Gauge("sensor_energy_kwh", "Energy in kW")

app = create_app(title="Sensor - Energy")

@app.get("/sensor/reading")
def reading():
    # Lightweight CPU work so flood requests produce measurable load
    sum(math.sqrt(i) * math.log(i + 1) for i in range(1, 50001))
    value = round(random.uniform(0.5, 15.0), 2)
    sensor_energy_kwh.set(value)
    return {"type": "energy", "value": value, "unit": "kW"}
