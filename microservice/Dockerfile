FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY base_app.py .
COPY sensors/ ./sensors/
ENV SENSOR_TYPE=temperature
EXPOSE 8080
CMD ["sh", "-c", "uvicorn sensors.${SENSOR_TYPE}:app --host 0.0.0.0 --port 8080"]
