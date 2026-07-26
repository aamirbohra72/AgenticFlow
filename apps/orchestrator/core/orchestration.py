"""
Shared orchestration pipeline used by POST /api/query/ and conversation reprocess.

Supports:
- Specialist routing via RabbitMQ
- Refund → Inventory fan-out (A2A via broker, not HTTP)
- Escalation to AutoGen agent when rules fire
"""

from __future__ import annotations

import logging

from django.utils import timezone

from core.escalation import build_escalation_payload, should_escalate
from core.intent import classify_intent
from core.models import ConversationLog
from core.rabbitmq_client import (
    QUEUE_MAP,
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
    # Best-effort seeds used in demo data
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
) -> list[dict]:
    """
    After a refund result, ask the Inventory Agent via RabbitMQ when a
    replacement is proposed (or inventory status is missing). This keeps
    A2A on the broker instead of direct HTTP between agents.
    """
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
    inventory_task = {
        "conversation_id": conversation_id,
        "query_text": query_text,
        "order_id": order_id,
        "intent": "inventory",
        "context": {
            "item_name": item_name,
            "source": "refund_fanout",
        },
    }

    reset_result_waiter(conversation_id)
    publish_task(QUEUE_MAP["inventory"], inventory_task)
    inventory_result = wait_for_result(
        conversation_id,
        timeout=RESULT_TIMEOUT,
        agent_name="inventory_agent",
    )
    agent_results.append(inventory_result)

    # Enrich refund payload with live inventory so escalation rules see it
    inv_payload = inventory_result.get("result_payload") or {}
    payload["inventory_status"] = {
        "item_name": inv_payload.get("item_name"),
        "in_stock": inv_payload.get("in_stock"),
        "quantity_available": inv_payload.get("quantity_available"),
        "restock_eta": inv_payload.get("restock_eta"),
    }
    refund["result_payload"] = payload
    return agent_results


def run_conversation_pipeline(log: ConversationLog) -> ConversationLog:
    """
    Drive one conversation from intent → specialist(s) → optional escalation.
    Mutates and returns the ConversationLog row.
    """
    query_text = log.query_text
    intent_result = classify_intent(query_text)
    conversation_id = str(log.conversation_id)

    log.intent = intent_result.intent
    log.status = ConversationLog.Status.IN_PROGRESS
    log.was_escalated = False
    log.agents_involved = []
    log.last_agent_name = ""
    log.confidence_score = None
    log.final_response = None
    log.save()

    queue = QUEUE_MAP.get(intent_result.intent, QUEUE_MAP["order"])
    task_payload = {
        "conversation_id": conversation_id,
        "query_text": query_text,
        "order_id": intent_result.order_id,
        "intent": intent_result.intent,
        "context": {
            "item_name": intent_result.item_name,
        },
    }

    register_result_waiter(conversation_id)
    agent_results: list[dict] = []

    try:
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
            )
            result = agent_results[0]

        if should_escalate(result, agent_results):
            log.status = ConversationLog.Status.ESCALATED
            log.was_escalated = True
            log.save(update_fields=["status", "was_escalated", "updated_at"])

            escalation_payload = build_escalation_payload(
                conversation_id=conversation_id,
                query_text=query_text,
                order_id=intent_result.order_id,
                agent_results=agent_results,
            )
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
        log.updated_at = timezone.now()
        log.save()
        return log

    finally:
        unregister_result_waiter(conversation_id)
