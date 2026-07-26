"""Deterministic refund eligibility (no LLM)."""

from datetime import date

from db import get_inventory_status, get_order_by_id, get_refund_policy


def compute_eligibility(order_id: str | None) -> tuple[dict, float]:
    """Deterministic eligibility + confidence before/alongside CrewAI summary."""
    if not order_id:
        return {
            "eligible": False,
            "reason": "No order ID provided",
            "replacement_proposed": False,
            "requires_escalation": True,
            "inventory_status": {},
            "summary": "Unable to process refund without an order ID.",
        }, 0.3

    order = get_order_by_id(order_id)
    if not order:
        return {
            "eligible": False,
            "reason": f"Order {order_id} not found",
            "replacement_proposed": False,
            "requires_escalation": True,
            "inventory_status": {},
            "summary": f"Order {order_id} was not found in our system.",
        }, 0.4

    policy = get_refund_policy(order["item_category"])
    inventory = get_inventory_status(order["item_name"])

    if not policy:
        return {
            "eligible": False,
            "reason": "No refund policy for item category",
            "replacement_proposed": False,
            "requires_escalation": True,
            "inventory_status": inventory,
            "summary": "We could not find a refund policy for this product category.",
        }, 0.4

    days_since = (date.today() - order["order_date"]).days
    within_window = days_since <= policy["refund_window_days"]
    # Propose replacement when outside the refund window; escalation handles OOS conflict
    replacement_proposed = not within_window

    if within_window and not policy["requires_manager_approval"]:
        eligible, confidence, reason = True, 0.9, "Within refund window, no manager approval needed"
    elif within_window and policy["requires_manager_approval"]:
        eligible, confidence, reason = True, 0.7, "Within window but requires manager approval"
    elif replacement_proposed and inventory.get("in_stock"):
        eligible, confidence, reason = False, 0.5, "Outside window; replacement offered instead of refund"
    else:
        eligible, confidence, reason = (
            False,
            0.4,
            "Outside refund window and no replacement available (out of stock)",
        )

    summary = (
        f"Order #{order_id} ({order['item_name']}): {reason}. "
        f"Days since order: {days_since}, policy window: {policy['refund_window_days']} days. "
        f"Inventory in stock: {inventory.get('in_stock')}."
    )

    return {
        "eligible": eligible,
        "reason": reason,
        "replacement_proposed": replacement_proposed,
        "requires_escalation": confidence < 0.6 or (replacement_proposed and not inventory.get("in_stock")),
        "inventory_status": inventory,
        "order_id": order_id,
        "item_name": order["item_name"],
        "summary": summary,
    }, confidence
