# Multi-stage build — 1GB RAM optimized
FROM python:3.12-slim AS builder

RUN apt-get update && apt-get install -y --no-install-recommends \
    libgomp1 libatomic1 && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Runtime stage
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    libgomp1 libatomic1 && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy layered deps
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy app
COPY . .

# Non-root user
RUN groupadd -r acml && useradd -r -g acml -d /app -s /sbin/nologin acml && \
    chown -R acml:acml /app
USER acml

# Single worker — critical for 1GB RAM
CMD ["uvicorn", "cloud.server:app", "--host", "0.0.0.0", "--port", "8080", \
     "--workers", "1", "--limit-concurrency", "16", \
     "--max-requests", "10000", "--timeout-keep-alive", "5"]

HEALTHCHECK --interval=30s --timeout=3s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/v1/health')"
