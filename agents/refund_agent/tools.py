from datetime import date

from crewai.tools import tool

from db import get_inventory_status, get_order_by_id, get_refund_policy


@tool("lookup_refund_eligibility")
def lookup_refund_eligibility(order_id: str) -> str:
    """Look up order details, refund policy, and inventory for a refund request."""
    order = get_order_by_id(order_id)
    if not order:
        return f"Order {order_id} not found."

    policy = get_refund_policy(order["item_category"])
    if not policy:
        return f"Order found but no refund policy for category '{order['item_category']}'."

    days_since = (date.today() - order["order_date"]).days
    within_window = days_since <= policy["refund_window_days"]
    inventory = get_inventory_status(order["item_name"])

    return (
        f"Order #{order['id']}: item={order['item_name']}, category={order['item_category']}, "
        f"status={order['status']}, days_since_order={days_since}, "
        f"refund_window_days={policy['refund_window_days']}, within_window={within_window}, "
        f"requires_manager_approval={policy['requires_manager_approval']}, "
        f"inventory_in_stock={inventory['in_stock']}, quantity={inventory['quantity_available']}"
    )
