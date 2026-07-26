FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app:/agents

COPY agents/escalation_agent/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

COPY agents/common /agents/common
COPY agents/escalation_agent /app

EXPOSE 5004
CMD ["python", "app.py"]
