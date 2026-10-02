FROM python:3.11-slim
RUN groupadd -r workload && useradd -r -g workload -d /app -s /sbin/nologin workload
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
USER workload
EXPOSE 8081
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8081"]
