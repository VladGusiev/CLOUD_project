import random
from prometheus_client import Gauge
from base_app import create_app

sensor_co2_ppm = Gauge("sensor_co2_ppm", "CO2 in ppm")
sensor_pm25 = Gauge("sensor_pm25", "PM2.5 concentration")

app = create_app(title="Sensor - Air Quality")

@app.get("/sensor/reading")
def reading():
    co2 = round(random.uniform(400.0, 2000.0), 1)
    pm25 = round(random.uniform(5.0, 150.0), 1)
    sensor_co2_ppm.set(co2)
    sensor_pm25.set(pm25)
    return {"type": "air_quality", "co2_ppm": co2, "pm25": pm25}
