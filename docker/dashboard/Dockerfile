# cloudphone dashboard + orchestrator API.
FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
        android-tools-adb iptables \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY orchestrator/ /app/orchestrator/
COPY README.md /app/README.md
RUN pip install --no-cache-dir -e /app/orchestrator

EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD python -c "import httpx,sys; sys.exit(0 if httpx.get('http://127.0.0.1:8080/healthz').status_code==200 else 1)"

CMD ["uvicorn", "cloudphone.server:app", "--host", "0.0.0.0", "--port", "8080"]
