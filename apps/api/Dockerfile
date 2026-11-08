# =============================================================================
# OpsPilot API — Multi-stage Dockerfile
# =============================================================================
FROM python:3.11-slim AS base

# Security: run as non-root
RUN groupadd -r opspilot && useradd -r -g opspilot -d /app -s /sbin/nologin opspilot

WORKDIR /app

# Install system deps for asyncpg / psycopg
RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc libpq-dev && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Bake the embedding model into the image (~130 MB) so containers start without
# network access to Hugging Face and every replica embeds identically (D-027).
ENV EMBEDDING_CACHE_DIR=/opt/models HF_HUB_DISABLE_TELEMETRY=1
RUN mkdir -p /opt/models &&     python -c "from fastembed import TextEmbedding; TextEmbedding('BAAI/bge-small-en-v1.5', cache_dir='/opt/models')" &&     chown -R opspilot:opspilot /opt/models

COPY . .

# Switch to non-root user
USER opspilot

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import httpx; r = httpx.get('http://localhost:8000/health'); r.raise_for_status()"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
