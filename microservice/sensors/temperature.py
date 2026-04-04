import random
from prometheus_client import Gauge
from base_app import create_app

sensor_temperature_celsius = Gauge("sensor_temperature_celsius", "Temperature in Celsius")

app = create_app(title="Sensor - Temperature")

@app.get("/sensor/reading")
def reading():
    value = round(random.uniform(18.0, 28.0), 1)
    sensor_temperature_celsius.set(value)
    return {"type": "temperature", "value": value, "unit": "C"}
