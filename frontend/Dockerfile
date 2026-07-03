# Separate image for the OPTIONAL dashboard — NOT part of the graded path.
# Kept out of the root Dockerfile so the graded pipeline image stays lean;
# this one carries the heavier streamlit/pandas/numpy/pyarrow stack instead.
# Build context is the repo root (see docker-compose.yml), since this image
# still needs the full `app/` package to run the pipeline via subprocess.

FROM --platform=linux/amd64 python:3.11-slim AS builder
WORKDIR /app
COPY requirements.txt ./requirements.txt
COPY frontend/requirements.txt ./frontend-requirements.txt
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt -r frontend-requirements.txt

FROM --platform=linux/amd64 python:3.11-slim
WORKDIR /app
COPY --from=builder /install /usr/local
COPY . .

ENV REPLAY_LLM=true
ENV SEED_DIR=/app/seed

CMD ["streamlit", "run", "frontend/streamlit_app.py", "--server.address=0.0.0.0", "--server.headless=true"]
