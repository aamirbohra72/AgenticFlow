"""
RabbitMQ client — the core A2A (agent-to-agent) message transport.

Django publishes task messages to specialist queues (order.tasks, etc.).
Flask agents consume those tasks and publish results to orchestrator.results.
A background thread in Django consumes orchestrator.results and wakes waiting API views.

v2 upgrade path: use correlation_id + per-conversation reply queues instead of
requeueing unrelated messages on a shared results queue.
"""

import json
import logging
import os
import threading
import time
from datetime import datetime, timezone

import pika

logger = logging.getLogger(__name__)

RESULTS_QUEUE = "orchestrator.results"

QUEUE_MAP = {
    "order": "order.tasks",
    "inventory": "inventory.tasks",
    "refund": "refund.tasks",
    "escalation": "escalation.tasks",
}

# In-memory registry: conversation_id -> (threading.Event, result dict)
_result_waiters: dict[str, tuple[threading.Event, dict]] = {}
_waiters_lock = threading.Lock()


def _get_rabbitmq_url() -> str:
    return os.getenv("RABBITMQ_URL", "amqp://guest:guest@localhost:5672/")


def _connect() -> pika.BlockingConnection:
    params = pika.URLParameters(_get_rabbitmq_url())
    return pika.BlockingConnection(params)


def publish_task(queue: str, payload: dict) -> None:
    """
    Publish a durable JSON task message to the given queue.

    This is the outbound A2A call: Django -> specialist agent queue.
    Messages survive broker restarts (delivery_mode=2).
    """
    if "timestamp" not in payload:
        payload["timestamp"] = datetime.now(timezone.utc).isoformat()

    connection = _connect()
    try:
        channel = connection.channel()
        # Declare queue so first publisher doesn't fail if agent hasn't started yet
        channel.queue_declare(queue=queue, durable=True)
        channel.basic_publish(
            exchange="",
            routing_key=queue,
            body=json.dumps(payload).encode("utf-8"),
            properties=pika.BasicProperties(
                delivery_mode=2,  # persistent message
                content_type="application/json",
            ),
        )
        logger.info("Published task to %s for conversation %s", queue, payload.get("conversation_id"))
    finally:
        connection.close()


def publish_result(payload: dict) -> None:
    """Publish an agent result back to the orchestrator results queue."""
    if "timestamp" not in payload:
        payload["timestamp"] = datetime.now(timezone.utc).isoformat()

    connection = _connect()
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
    finally:
        connection.close()


def register_result_waiter(conversation_id: str) -> threading.Event:
    """Register a waiter before publishing a task so the consumer can signal it."""
    event = threading.Event()
    with _waiters_lock:
        _result_waiters[conversation_id] = (event, {})
    return event


def unregister_result_waiter(conversation_id: str) -> None:
    with _waiters_lock:
        _result_waiters.pop(conversation_id, None)


def notify_result_waiter(conversation_id: str, result: dict) -> None:
    """Called by the background consumer when a matching result arrives."""
    with _waiters_lock:
        entry = _result_waiters.get(conversation_id)
        if entry:
            event, store = entry
            store.update(result)
            event.set()


def wait_for_result(conversation_id: str, timeout: float = 30.0, agent_name: str | None = None) -> dict:
    """
    Block until a result for conversation_id arrives or timeout expires.

  Polls the in-memory Event set by the background consumer thread.
  Optionally filter by agent_name (e.g. wait specifically for escalation_agent).
    """
    with _waiters_lock:
        entry = _result_waiters.get(conversation_id)
        if not entry:
            register_result_waiter(conversation_id)
            entry = _result_waiters[conversation_id]

    event, store = entry
    deadline = time.monotonic() + timeout

    while time.monotonic() < deadline:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        if event.wait(timeout=min(1.0, remaining)):
            event.clear()
            if store:
                if agent_name is None or store.get("agent_name") == agent_name:
                    return dict(store)
                # Wrong agent — discard and keep waiting
                store.clear()
        elif store:
            if agent_name is None or store.get("agent_name") == agent_name:
                return dict(store)

    raise TimeoutError(f"No result received for conversation {conversation_id} within {timeout}s")


def consume_results_loop() -> None:
    """
    Long-running consumer loop for orchestrator.results.

    Runs in a daemon thread started from core.apps.CoreConfig.ready().
    Each message is routed to the waiting API view via notify_result_waiter().
    """
    from core.redis_client import append_trace

    while True:
        try:
            connection = _connect()
            channel = connection.channel()
            channel.queue_declare(queue=RESULTS_QUEUE, durable=True)
            channel.basic_qos(prefetch_count=1)

            def on_message(ch, method, properties, body):
                try:
                    result = json.loads(body.decode("utf-8"))
                    conversation_id = result.get("conversation_id")
                    agent_name = result.get("agent_name", "unknown")
                    payload = result.get("result_payload", {})
                    message = payload.get("summary") or payload.get("final_response") or str(payload)

                    logger.info("Received result from %s for %s", agent_name, conversation_id)

                    append_trace(conversation_id, agent_name, message)

                    if conversation_id:
                        notify_result_waiter(conversation_id, result)
                except Exception:
                    logger.exception("Error processing result message")
                finally:
                    ch.basic_ack(delivery_tag=method.delivery_tag)

            channel.basic_consume(queue=RESULTS_QUEUE, on_message_callback=on_message)
            logger.info("Result consumer listening on %s", RESULTS_QUEUE)
            channel.start_consuming()
        except Exception:
            logger.exception("Result consumer disconnected, retrying in 5s")
            time.sleep(5)
