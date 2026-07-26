"""
RabbitMQ client — the core A2A (agent-to-agent) message transport (v2).

Django publishes task messages to specialist queues (order.tasks, etc.).
Flask agents consume those tasks and publish results to orchestrator.results.
A background thread in Django consumes orchestrator.results and wakes waiting API views.

v2 adds:
- schema_version / correlation_id / attempt on every message
- dead-letter queues (*.dlq) for poison messages
- Redis-backed result wait + idempotency keys
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from datetime import datetime, timezone

import pika

logger = logging.getLogger(__name__)

RESULTS_QUEUE = "orchestrator.results.v2"
RESULTS_DLQ = "orchestrator.results.v2.dlq"
DLX_EXCHANGE = "agentic.dlx"
SCHEMA_VERSION = 2

QUEUE_MAP = {
    "order": "order.tasks.v2",
    "inventory": "inventory.tasks.v2",
    "refund": "refund.tasks.v2",
    "escalation": "escalation.tasks.v2",
}

TASK_QUEUES = list(QUEUE_MAP.values())

# In-memory registry: conversation_id -> (threading.Event, result dict)
_result_waiters: dict[str, tuple[threading.Event, dict]] = {}
_waiters_lock = threading.Lock()

# Health: set True once the result consumer enters start_consuming()
result_consumer_alive = False


def _get_rabbitmq_url() -> str:
    return os.getenv("RABBITMQ_URL", "amqp://guest:guest@localhost:5672/")


def _max_attempts() -> int:
    return int(os.getenv("MESSAGE_MAX_ATTEMPTS", "3"))


def _connect() -> pika.BlockingConnection:
    params = pika.URLParameters(_get_rabbitmq_url())
    return pika.BlockingConnection(params)


def _dlq_name(queue: str) -> str:
    return f"{queue}.dlq"


def declare_queue_with_dlq(channel, queue: str, connection=None):
    """
    Declare durable queue + DLQ via named exchange ``agentic.dlx``.

    Uses a named DLX (not the default exchange "") to avoid RabbitMQ
    PRECONDITION_FAILED mismatches where empty-string DLX is compared as ``none``.

    On PRECONDITION_FAILED, delete and recreate when ``connection`` is provided.
    Returns a usable channel (may be a new one after recreate).
    """
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


def build_task_payload(
    *,
    conversation_id: str,
    query_text: str,
    intent: str,
    order_id: str | None = None,
    context: dict | None = None,
    correlation_id: str | None = None,
    attempt: int = 1,
) -> dict:
    """Canonical v2 task message schema."""
    return {
        "schema_version": SCHEMA_VERSION,
        "conversation_id": conversation_id,
        "correlation_id": correlation_id or f"{conversation_id}:{uuid.uuid4()}",
        "query_text": query_text,
        "order_id": order_id,
        "intent": intent,
        "attempt": attempt,
        "context": context or {},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def publish_task(queue: str, payload: dict) -> None:
    """
    Publish a durable JSON task message to the given queue.

    Does not declare the queue — consumers own topology (avoids DLX arg clashes).
    """
    payload.setdefault("schema_version", SCHEMA_VERSION)
    payload.setdefault("timestamp", datetime.now(timezone.utc).isoformat())
    payload.setdefault("attempt", 1)
    if not payload.get("correlation_id"):
        cid = payload.get("conversation_id", "unknown")
        payload["correlation_id"] = f"{cid}:{uuid.uuid4()}"

    connection = _connect()
    try:
        channel = connection.channel()
        channel.confirm_delivery()
        channel.basic_publish(
            exchange="",
            routing_key=queue,
            body=json.dumps(payload).encode("utf-8"),
            properties=pika.BasicProperties(
                delivery_mode=2,
                content_type="application/json",
                correlation_id=payload["correlation_id"],
                headers={"schema_version": SCHEMA_VERSION, "attempt": payload.get("attempt", 1)},
            ),
            mandatory=True,
        )
        logger.info(
            "Published task queue=%s conversation_id=%s correlation_id=%s",
            queue,
            payload.get("conversation_id"),
            payload.get("correlation_id"),
        )
    finally:
        connection.close()


def publish_result(payload: dict) -> None:
    """Publish an agent result back to the orchestrator results queue (no declare)."""
    payload.setdefault("schema_version", SCHEMA_VERSION)
    payload.setdefault("timestamp", datetime.now(timezone.utc).isoformat())
    if not payload.get("correlation_id") and payload.get("conversation_id"):
        payload["correlation_id"] = f"{payload['conversation_id']}:{uuid.uuid4()}"

    connection = _connect()
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


def reset_result_waiter(conversation_id: str) -> threading.Event:
    """Clear any prior result so the next wait_for_result() blocks for a new agent."""
    unregister_result_waiter(conversation_id)
    return register_result_waiter(conversation_id)


def check_rabbitmq() -> dict:
    """Lightweight connectivity check for the health endpoint."""
    try:
        connection = _connect()
        connection.close()
        return {"ok": True, "detail": "connected"}
    except Exception as exc:
        return {"ok": False, "detail": str(exc)}


def notify_result_waiter(conversation_id: str, result: dict) -> None:
    """Called by the background consumer when a matching result arrives."""
    with _waiters_lock:
        entry = _result_waiters.get(conversation_id)
        if entry:
            event, store = entry
            store.clear()
            store.update(result)
            event.set()


def wait_for_result(conversation_id: str, timeout: float = 30.0, agent_name: str | None = None) -> dict:
    """
    Block until a result for conversation_id arrives or timeout expires.

    Primary path: in-memory Event set by the background consumer thread.
    Fallback: poll Redis `result:{conversation_id}` (survives duplicate consumers).
    """
    from core.redis_client import get_stored_result

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
                store.clear()
        elif store:
            if agent_name is None or store.get("agent_name") == agent_name:
                return dict(store)

        cached = get_stored_result(conversation_id)
        if cached and (agent_name is None or cached.get("agent_name") == agent_name):
            return cached

    raise TimeoutError(f"No result received for conversation {conversation_id} within {timeout}s")


def consume_results_loop() -> None:
    """
    Long-running consumer loop for orchestrator.results.

    Runs in a daemon thread started from core.apps.CoreConfig.ready().
    """
    global result_consumer_alive
    from core.redis_client import append_trace, mark_processed, store_result, was_processed

    print(f"[orchestrator] Result consumer starting on {RESULTS_QUEUE}", flush=True)
    while True:
        try:
            connection = _connect()
            channel = connection.channel()
            channel = declare_queue_with_dlq(channel, RESULTS_QUEUE, connection)
            channel.basic_qos(prefetch_count=1)

            def on_message(ch, method, properties, body):
                try:
                    result = json.loads(body.decode("utf-8"))
                    conversation_id = result.get("conversation_id")
                    agent_name = result.get("agent_name", "unknown")
                    correlation_id = result.get("correlation_id") or (
                        properties.correlation_id if properties else None
                    )
                    payload = result.get("result_payload", {})
                    message = payload.get("summary") or payload.get("final_response") or str(payload)

                    # Idempotency: skip duplicate deliveries of the same correlation+agent
                    idem_key = f"{correlation_id}:{agent_name}" if correlation_id else None
                    if idem_key and was_processed(idem_key):
                        logger.info("Skipping duplicate result %s", idem_key)
                        ch.basic_ack(delivery_tag=method.delivery_tag)
                        return

                    logger.info(
                        "Received result agent=%s conversation_id=%s correlation_id=%s",
                        agent_name,
                        conversation_id,
                        correlation_id,
                    )
                    print(
                        f"[orchestrator] Received result from {agent_name} for {conversation_id}",
                        flush=True,
                    )

                    if conversation_id:
                        store_result(conversation_id, result)
                        append_trace(conversation_id, agent_name, message)
                        notify_result_waiter(conversation_id, result)
                    if idem_key:
                        mark_processed(idem_key)

                    ch.basic_ack(delivery_tag=method.delivery_tag)
                except Exception:
                    logger.exception("Error processing result message — sending to DLQ")
                    # negative ack without requeue → dead-letter exchange routes to DLQ
                    ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)

            channel.basic_consume(queue=RESULTS_QUEUE, on_message_callback=on_message)
            logger.info("Result consumer listening on %s", RESULTS_QUEUE)
            print(f"[orchestrator] Result consumer listening on {RESULTS_QUEUE}", flush=True)
            result_consumer_alive = True
            channel.start_consuming()
        except Exception:
            result_consumer_alive = False
            logger.exception("Result consumer disconnected, retrying in 5s")
            print("[orchestrator] Result consumer disconnected, retrying in 5s", flush=True)
            time.sleep(5)
