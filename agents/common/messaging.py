"""
Shared RabbitMQ helpers for Flask agent services.

Each agent runs its own consumer loop on a dedicated task queue and publishes
results back to orchestrator.results — the same A2A pattern as Django's client.
"""

import json
import logging
import os
from datetime import datetime, timezone

import pika

logger = logging.getLogger(__name__)

RESULTS_QUEUE = "orchestrator.results"


def get_rabbitmq_url() -> str:
    return os.getenv("RABBITMQ_URL", "amqp://guest:guest@localhost:5672/")


def connect() -> pika.BlockingConnection:
    return pika.BlockingConnection(pika.URLParameters(get_rabbitmq_url()))


def publish_result(payload: dict) -> None:
    """Publish agent result to orchestrator.results for Django to consume."""
    if "timestamp" not in payload:
        payload["timestamp"] = datetime.now(timezone.utc).isoformat()

    connection = connect()
    try:
        channel = connection.channel()
        channel.queue_declare(queue=RESULTS_QUEUE, durable=True)
        channel.basic_publish(
            exchange="",
            routing_key=RESULTS_QUEUE,
            body=json.dumps(payload).encode("utf-8"),
            properties=pika.BasicProperties(
                delivery_mode=2,
                content_type="application/json",
            ),
        )
        logger.info(
            "Published result from %s for conversation %s",
            payload.get("agent_name"),
            payload.get("conversation_id"),
        )
    finally:
        connection.close()


def start_consumer(queue_name: str, handler) -> None:
    """
    Blocking consumer loop on the given task queue.

    handler(task_payload: dict) -> result_payload dict
    The handler should return the result_payload; this function wraps it
  in the standard result envelope and publishes to orchestrator.results.
    """
    while True:
        try:
            connection = connect()
            channel = connection.channel()
            channel.queue_declare(queue=queue_name, durable=True)
            channel.basic_qos(prefetch_count=1)

            def on_message(ch, method, properties, body):
                try:
                    task = json.loads(body.decode("utf-8"))
                    logger.info("Received task on %s: %s", queue_name, task.get("conversation_id"))
                    result_payload, confidence_score, agent_name = handler(task)
                    publish_result(
                        {
                            "conversation_id": task["conversation_id"],
                            "agent_name": agent_name,
                            "result_payload": result_payload,
                            "confidence_score": confidence_score,
                        }
                    )
                except Exception:
                    logger.exception("Error handling task on %s", queue_name)
                finally:
                    ch.basic_ack(delivery_tag=method.delivery_tag)

            channel.basic_consume(queue=queue_name, on_message_callback=on_message)
            logger.info("Consumer listening on %s", queue_name)
            channel.start_consuming()
        except Exception:
            logger.exception("Consumer disconnected on %s, retrying in 5s", queue_name)
            import time

            time.sleep(5)
