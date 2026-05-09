import math
import random
from prometheus_client import Gauge
from base_app import create_app

sensor_humidity_percent = Gauge("sensor_humidity_percent", "Humidity percent")

app = create_app(title="Sensor - Humidity")

@app.get("/sensor/reading")
def reading():
    # Lightweight CPU work so flood requests produce measurable load
    sum(math.sqrt(i) * math.log(i + 1) for i in range(1, 50001))
    value = round(random.uniform(30.0, 80.0), 1)
    sensor_humidity_percent.set(value)
    return {"type": "humidity", "value": value, "unit": "%"}
