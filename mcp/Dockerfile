# =============================================================================
# OpsPilot MCP Server — Dockerfile
# Read-only operational tools over Streamable HTTP (port 8001).
# =============================================================================
FROM python:3.11-slim

RUN groupadd -r opspilot && useradd -r -g opspilot -d /app -s /sbin/nologin opspilot

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

# Security updates for the base OS, and current packaging tools (the base image's
# bundled wheel/setuptools carry advisories; Phase 11 Trivy scan, D-038).
RUN apt-get update && apt-get upgrade -y && rm -rf /var/lib/apt/lists/* && \
    pip install --no-cache-dir --upgrade pip setuptools wheel

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY opsmcp ./opsmcp

USER opspilot

EXPOSE 8001

HEALTHCHECK --interval=10s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8001/health', timeout=3)"

CMD ["uvicorn", "opsmcp.server:app", "--host", "0.0.0.0", "--port", "8001", "--no-access-log"]
