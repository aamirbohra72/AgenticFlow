FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV CREWAI_TESTING=true
ENV CREWAI_TRACING_ENABLED=false
ENV OTEL_SDK_DISABLED=true
ENV PYTHONPATH=/app:/agents

COPY agents/inventory_agent/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

COPY agents/common /agents/common
COPY agents/inventory_agent /app

EXPOSE 5002
CMD ["python", "app.py"]
