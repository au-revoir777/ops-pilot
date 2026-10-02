# =============================================================================
# OpsPilot MCP Server — Dockerfile
# =============================================================================
FROM python:3.11-slim

RUN groupadd -r opspilot && useradd -r -g opspilot -d /app -s /sbin/nologin opspilot

WORKDIR /app

RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

USER opspilot

EXPOSE 8001

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import httpx; r = httpx.get('http://localhost:8001/health'); r.raise_for_status()"

CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8001"]
