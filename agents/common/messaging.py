"""
Shared RabbitMQ helpers for Flask agent services (v2).

Adds schema_version, correlation_id, attempt, and DLQ via named exchange agentic.dlx.
On handler failure, nack without requeue after max attempts so messages land in *.dlq.
Publishers do not declare queues — consumers own topology.
"""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from datetime import datetime, timezone

import pika

logger = logging.getLogger(__name__)

RESULTS_QUEUE = "orchestrator.results.v2"
DLX_EXCHANGE = "agentic.dlx"
SCHEMA_VERSION = 2


def get_rabbitmq_url() -> str:
    return os.getenv("RABBITMQ_URL", "amqp://guest:guest@localhost:5672/")


def _max_attempts() -> int:
    return int(os.getenv("MESSAGE_MAX_ATTEMPTS", "3"))


def connect() -> pika.BlockingConnection:
    return pika.BlockingConnection(pika.URLParameters(get_rabbitmq_url()))


def _dlq_name(queue: str) -> str:
    return f"{queue}.dlq"


def declare_queue_with_dlq(channel, queue: str, connection=None):
    """Declare durable queue + DLQ via named exchange. Recreate on PRECONDITION_FAILED."""
    dlq = _dlq_name(queue)
    args = {
        "x-dead-letter-exchange": DLX_EXCHANGE,
        "x-dead-letter-routing-key": dlq,
    }

    def _declare(ch):
        ch.exchange_declare(exchange=DLX_EXCHANGE, exchange_type="direct", durable=True)
        ch.queue_declare(queue=dlq, durable=True)
        ch.queue_bind(exchange=DLX_EXCHANGE, queue=dlq, routing_key=dlq)
        ch.queue_declare(queue=queue, durable=True, arguments=args)
        return ch

    try:
        return _declare(channel)
    except pika.exceptions.ChannelClosedByBroker as exc:
        if connection is None or "PRECONDITION_FAILED" not in str(exc):
            raise
        logger.warning("Queue %s has incompatible args; recreating with named DLX", queue)
        channel = connection.channel()
        try:
            channel.queue_delete(queue=queue)
        except Exception:
            logger.exception("Failed deleting incompatible queue %s", queue)
        return _declare(channel)


def publish_result(payload: dict) -> None:
    """Publish agent result to orchestrator.results (no declare — consumer owns topology)."""
    payload.setdefault("schema_version", SCHEMA_VERSION)
    payload.setdefault("timestamp", datetime.now(timezone.utc).isoformat())
    if not payload.get("correlation_id") and payload.get("conversation_id"):
        payload["correlation_id"] = f"{payload['conversation_id']}:{uuid.uuid4()}"

    connection = connect()
    try:
        channel = connection.channel()
        channel.confirm_delivery()
        channel.basic_publish(
            exchange="",
            routing_key=RESULTS_QUEUE,
            body=json.dumps(payload).encode("utf-8"),
            properties=pika.BasicProperties(
                delivery_mode=2,
                content_type="application/json",
                correlation_id=payload.get("correlation_id"),
            ),
            mandatory=True,
        )
        logger.info(
            "Published result agent=%s conversation_id=%s correlation_id=%s",
            payload.get("agent_name"),
            payload.get("conversation_id"),
            payload.get("correlation_id"),
        )
    finally:
        connection.close()


def start_consumer(queue_name: str, handler) -> None:
    """
    Blocking consumer loop on the given task queue.

    handler(task_payload: dict) -> (result_payload, confidence_score, agent_name)
    """
    while True:
        try:
            connection = connect()
            channel = connection.channel()
            channel = declare_queue_with_dlq(channel, queue_name, connection)
            channel.basic_qos(prefetch_count=1)

            def on_message(ch, method, properties, body):
                task = {}
                try:
                    task = json.loads(body.decode("utf-8"))
                    attempt = int(task.get("attempt") or 1)
                    correlation_id = task.get("correlation_id") or (
                        properties.correlation_id if properties else None
                    )
                    logger.info(
                        "Received task queue=%s conversation_id=%s correlation_id=%s attempt=%s",
                        queue_name,
                        task.get("conversation_id"),
                        correlation_id,
                        attempt,
                    )
                    result_payload, confidence_score, agent_name = handler(task)
                    publish_result(
                        {
                            "schema_version": SCHEMA_VERSION,
                            "conversation_id": task["conversation_id"],
                            "correlation_id": correlation_id,
                            "agent_name": agent_name,
                            "result_payload": result_payload,
                            "confidence_score": confidence_score,
                            "attempt": attempt,
                        }
                    )
                    ch.basic_ack(delivery_tag=method.delivery_tag)
                except Exception:
                    logger.exception("Error handling task on %s", queue_name)
                    attempt = int(task.get("attempt") or 1) if task else 1
                    if attempt >= _max_attempts():
                        ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)
                    else:
                        try:
                            task["attempt"] = attempt + 1
                            ch.basic_publish(
                                exchange="",
                                routing_key=queue_name,
                                body=json.dumps(task).encode("utf-8"),
                                properties=pika.BasicProperties(
                                    delivery_mode=2,
                                    content_type="application/json",
                                    correlation_id=task.get("correlation_id"),
                                    headers={"attempt": task["attempt"]},
                                ),
                            )
                            ch.basic_ack(delivery_tag=method.delivery_tag)
                        except Exception:
                            logger.exception("Failed to requeue attempt — DLQ")
                            ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)

            channel.basic_consume(queue=queue_name, on_message_callback=on_message)
            logger.info("Consumer listening on %s", queue_name)
            channel.start_consuming()
        except Exception:
            logger.exception("Consumer disconnected on %s, retrying in 5s", queue_name)
            time.sleep(5)
