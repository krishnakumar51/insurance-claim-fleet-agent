# Reference skeleton — adapt to your stack (any language is fine).
# HARD RULE: the graded path must run with ONE command on a fresh, network-restricted
# machine: `docker compose up`. Pin to linux/amd64 so it builds identically on our box.
#
# Multi-stage: dependencies are installed into an isolated prefix in the builder
# stage (pip cache, wheel build artifacts, apt lists never enter the final image),
# then only the installed packages are copied into a clean runtime layer. This
# image is ALSO deliberately lean-only-the-graded-path: the dashboard's heavier
# deps (streamlit/pandas/numpy/pyarrow) live in their own separate image
# (frontend/Dockerfile), not here.

FROM --platform=linux/amd64 python:3.11-slim AS builder
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

FROM --platform=linux/amd64 python:3.11-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends make && rm -rf /var/lib/apt/lists/*
COPY --from=builder /install /usr/local
COPY . .

# Offline replay is the default graded path. Graders flip REPLAY_LLM=false + provide a key
# for the held-out run, and swap the seed via SEED_DIR.
ENV REPLAY_LLM=true
ENV SEED_DIR=/app/seed

# Must produce /app/out/<package>, /app/out/audit.json, /app/out/exception_queue.json
# and self-verify. Replace with your own entrypoint if you don't use make.
CMD ["sh", "-c", "make demo && make verify"]
