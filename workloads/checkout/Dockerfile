FROM python:3.11-slim

RUN groupadd -r workload && useradd -r -g workload -d /app -s /sbin/nologin workload

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

USER workload

ARG PORT=8080
EXPOSE ${PORT}

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
