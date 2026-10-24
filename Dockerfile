FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY pipeline.py config.yaml ./
COPY examples ./examples
# /data holds papers.sqlite (the dedup record) and out/ (review queues). Mount it as a volume.
# Use another config by appending e.g. `--config /app/examples/ldct/config.yaml` to docker run.
VOLUME ["/data"]
ENTRYPOINT ["python", "pipeline.py", "--config", "/app/config.yaml", "--data", "/data"]
