"""
Shared orchestration pipeline used by POST /api/query/ and conversation reprocess (v2).

Supports:
- Specialist routing via RabbitMQ with correlation_id
- Refund → Inventory fan-out (A2A via broker, not HTTP)
- Escalation to AutoGen agent when rules fire
- failed status on timeout
"""

from __future__ import annotations

import logging
import uuid

from django.utils import timezone

from core.escalation import build_escalation_payload, should_escalate
from core.intent import classify_intent
from core.metrics import Timer, incr
from core.models import ConversationLog
from core.rabbitmq_client import (
    QUEUE_MAP,
    build_task_payload,
    publish_task,
    register_result_waiter,
    reset_result_waiter,
    unregister_result_waiter,
    wait_for_result,
)

logger = logging.getLogger(__name__)

RESULT_TIMEOUT = 90.0


def format_response(result: dict) -> str:
    payload = result.get("result_payload", {})
    if isinstance(payload.get("summary"), str):
        return payload["summary"]
    if isinstance(payload.get("final_response"), str):
        return payload["final_response"]
    if isinstance(payload.get("message"), str):
        return payload["message"]
    return str(payload)


def _item_name_from_results(query_text: str, intent_item: str | None, agent_results: list[dict]) -> str | None:
    if intent_item:
        return intent_item
    for result in agent_results:
        payload = result.get("result_payload") or {}
        if payload.get("item_name"):
            return payload["item_name"]
    for seed in ("Wireless Headphones", "Running Shoes", "Smart Watch", "Laptop Stand"):
        if seed.lower() in query_text.lower():
            return seed
    return None


def _maybe_fanout_inventory(
    conversation_id: str,
    query_text: str,
    order_id: str | None,
    intent_item: str | None,
    agent_results: list[dict],
    base_correlation_id: str,
) -> list[dict]:
    refund = agent_results[-1]
    if refund.get("agent_name") != "refund_agent":
        return agent_results

    payload = refund.get("result_payload") or {}
    inventory_status = payload.get("inventory_status") or {}
    needs_inventory = (
        payload.get("replacement_proposed")
        or inventory_status.get("in_stock") is None
        or payload.get("requires_escalation")
    )

    if not needs_inventory:
        return agent_results

    item_name = _item_name_from_results(query_text, intent_item, agent_results)
    inventory_task = build_task_payload(
        conversation_id=conversation_id,
        query_text=query_text,
        intent="inventory",
        order_id=order_id,
        correlation_id=f"{base_correlation_id}:inventory:{uuid.uuid4()}",
        context={
            "item_name": item_name,
            "source": "refund_fanout",
        },
    )

    reset_result_waiter(conversation_id)
    publish_task(QUEUE_MAP["inventory"], inventory_task)
    inventory_result = wait_for_result(
        conversation_id,
        timeout=RESULT_TIMEOUT,
        agent_name="inventory_agent",
    )
    agent_results.append(inventory_result)

    inv_payload = inventory_result.get("result_payload") or {}
    payload["inventory_status"] = {
        "item_name": inv_payload.get("item_name"),
        "in_stock": inv_payload.get("in_stock"),
        "quantity_available": inv_payload.get("quantity_available"),
        "restock_eta": inv_payload.get("restock_eta"),
    }
    refund["result_payload"] = payload
    return agent_results


def run_conversation_pipeline(log: ConversationLog, request_id: str = "") -> ConversationLog:
    """
    Drive one conversation from intent → specialist(s) → optional escalation.
    Mutates and returns the ConversationLog row.
    """
    query_text = log.query_text
    intent_result = classify_intent(query_text)
    conversation_id = str(log.conversation_id)
    correlation_id = f"{conversation_id}:{uuid.uuid4()}"

    log.intent = intent_result.intent
    log.status = ConversationLog.Status.IN_PROGRESS
    log.was_escalated = False
    log.agents_involved = []
    log.last_agent_name = ""
    log.confidence_score = None
    log.final_response = None
    log.error_message = None
    if request_id:
        log.request_id = request_id
    log.save()

    incr(f"queries.intent.{intent_result.intent}")
    incr("queries.total")

    task_payload = build_task_payload(
        conversation_id=conversation_id,
        query_text=query_text,
        intent=intent_result.intent,
        order_id=intent_result.order_id,
        correlation_id=correlation_id,
        context={"item_name": intent_result.item_name, "request_id": request_id},
    )

    queue = QUEUE_MAP.get(intent_result.intent, QUEUE_MAP["order"])
    register_result_waiter(conversation_id)
    agent_results: list[dict] = []

    try:
        with Timer(f"pipeline.{intent_result.intent}"):
            publish_task(queue, task_payload)
            expected_agent = f"{intent_result.intent}_agent"
            result = wait_for_result(
                conversation_id,
                timeout=RESULT_TIMEOUT,
                agent_name=expected_agent,
            )
            agent_results = [result]

            if intent_result.intent == "refund":
                agent_results = _maybe_fanout_inventory(
                    conversation_id=conversation_id,
                    query_text=query_text,
                    order_id=intent_result.order_id,
                    intent_item=intent_result.item_name,
                    agent_results=agent_results,
                    base_correlation_id=correlation_id,
                )
                result = agent_results[0]

            if should_escalate(result, agent_results):
                incr("queries.escalated")
                log.status = ConversationLog.Status.ESCALATED
                log.was_escalated = True
                log.save(update_fields=["status", "was_escalated", "updated_at"])

                escalation_payload = build_escalation_payload(
                    conversation_id=conversation_id,
                    query_text=query_text,
                    order_id=intent_result.order_id,
                    agent_results=agent_results,
                )
                escalation_payload = {
                    **build_task_payload(
                        conversation_id=conversation_id,
                        query_text=query_text,
                        intent="escalation",
                        order_id=intent_result.order_id,
                        correlation_id=f"{correlation_id}:escalation:{uuid.uuid4()}",
                        context=escalation_payload.get("context", {}),
                    ),
                }
                reset_result_waiter(conversation_id)
                publish_task(QUEUE_MAP["escalation"], escalation_payload)
                escalation_result = wait_for_result(
                    conversation_id,
                    timeout=RESULT_TIMEOUT,
                    agent_name="escalation_agent",
                )
                agent_results.append(escalation_result)
                result = escalation_result

            final_response = format_response(result)
            agents_involved = [r.get("agent_name") for r in agent_results if r.get("agent_name")]

            log.final_response = final_response
            log.status = ConversationLog.Status.RESOLVED
            log.last_agent_name = result.get("agent_name") or ""
            log.confidence_score = result.get("confidence_score")
            log.agents_involved = agents_involved
            log.error_message = None
            log.updated_at = timezone.now()
            log.save()
            incr("queries.resolved")
            return log

    except TimeoutError as exc:
        incr("queries.timeout")
        logger.error("Pipeline timeout conversation_id=%s request_id=%s", conversation_id, request_id)
        log.status = ConversationLog.Status.FAILED
        log.error_message = str(exc)
        log.save(update_fields=["status", "error_message", "updated_at"])
        raise

    except Exception as exc:
        incr("queries.error")
        logger.exception("Pipeline error conversation_id=%s", conversation_id)
        log.status = ConversationLog.Status.FAILED
        log.error_message = str(exc)
        log.save(update_fields=["status", "error_message", "updated_at"])
        raise

    finally:
        unregister_result_waiter(conversation_id)
