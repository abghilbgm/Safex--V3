FROM python:3.11-slim
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg libsm6 libxext6 libgl1 libglib2.0-0 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app/ ./app/
COPY dashboard/ ./dashboard/
COPY scripts/ ./scripts/
RUN mkdir -p /app/models /app/data/snapshots
ENV PPE_SNAPSHOT_DIR=/app/data/snapshots
ENV PPE_MODEL_PATH=/app/models/best.pt
ENV PPE_API_HOST=0.0.0.0
ENV PPE_API_PORT=8080
EXPOSE 8080
CMD ["python", "-m", "app.main"]
