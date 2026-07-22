"""Escalation rules — when to route to the AutoGen escalation agent."""

ESCALATION_QUEUE = "escalation.tasks"
CONFIDENCE_THRESHOLD = 0.6


def should_escalate(result: dict, prior_results: list[dict] | None = None) -> bool:
    """
    Return True if the orchestrator should publish to escalation.tasks.

    Triggers:
    1. Refund agent confidence below threshold
    2. Refund proposes replacement but inventory shows out of stock
    """
    agent_name = result.get("agent_name", "")
    confidence = result.get("confidence_score", 1.0)
    payload = result.get("result_payload", {})

    if agent_name == "refund_agent" and confidence < CONFIDENCE_THRESHOLD:
        return True

    if agent_name == "refund_agent" and payload.get("replacement_proposed"):
        inventory_status = payload.get("inventory_status", {})
        if inventory_status.get("in_stock") is False:
            return True
        # Also check prior inventory agent result if present
        if prior_results:
            for prior in prior_results:
                if prior.get("agent_name") == "inventory_agent":
                    prior_payload = prior.get("result_payload", {})
                    if not prior_payload.get("in_stock", True):
                        return True

    return False


def build_escalation_payload(
    conversation_id: str,
    query_text: str,
    order_id: str | None,
    agent_results: list[dict],
) -> dict:
    """Build the task message for escalation.tasks."""
    return {
        "conversation_id": conversation_id,
        "query_text": query_text,
        "order_id": order_id,
        "intent": "escalation",
        "context": {
            "agent_results": agent_results,
            "reason": "low_confidence_or_inventory_conflict",
        },
    }
