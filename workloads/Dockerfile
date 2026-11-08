# =============================================================================
# OpsPilot demo workloads: one small image, three services.
# The service is chosen by the container command, e.g.
#   uvicorn opsdemo.checkout:app --host 0.0.0.0 --port 8080
# =============================================================================
FROM python:3.11-slim

RUN groupadd -r workload && useradd -r -g workload -d /app -s /sbin/nologin workload

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY opsdemo ./opsdemo

USER workload

# Default to checkout; Compose overrides the command per service.
ENV SERVICE_PORT=8080
EXPOSE 8080 8081 8082
HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ[\"SERVICE_PORT\"]}/health', timeout=2)"

CMD ["uvicorn", "opsdemo.checkout:app", "--host", "0.0.0.0", "--port", "8080"]
