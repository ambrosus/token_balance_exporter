# Build stage
FROM python:3.11-slim as builder

WORKDIR /app

# Install build dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc python3-dev && \
    rm -rf /var/lib/apt/lists/*

# Copy requirements and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# Final stage
FROM python:3.11-slim

WORKDIR /app

# Copy only the necessary files from builder
COPY --from=builder /root/.local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY src/ /app/src/
COPY config/ /app/config/

ENV CONFIG_PATH=/app/config/config.yaml
ENV PORT=4200

# Install curl for healthcheck (much smaller than gcc and python3-dev)
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl && \
    rm -rf /var/lib/apt/lists/*

EXPOSE 4200

HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:4200/health

CMD ["python", "-m", "src.main"]
