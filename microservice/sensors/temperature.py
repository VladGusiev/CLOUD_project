import math
import random
from prometheus_client import Gauge
from base_app import create_app

sensor_temperature_celsius = Gauge("sensor_temperature_celsius", "Temperature in Celsius")

app = create_app(title="Sensor - Temperature")

@app.get("/sensor/reading")
def reading():
    # Lightweight CPU work so flood requests produce measurable load
    sum(math.sqrt(i) * math.log(i + 1) for i in range(1, 50001))
    value = round(random.uniform(18.0, 28.0), 1)
    sensor_temperature_celsius.set(value)
    return {"type": "temperature", "value": value, "unit": "C"}
