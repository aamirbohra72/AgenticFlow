from crewai.tools import tool

from db import get_order_by_id


@tool("get_order_status")
def get_order_status(order_id: str) -> str:
    """Look up order status and tracking number by order ID."""
    order = get_order_by_id(order_id)
    if not order:
        return f"No order found with ID {order_id}."
    return (
        f"Order #{order['id']}: status={order['status']}, "
        f"item={order['item_name']}, customer={order['customer_name']}, "
        f"tracking={order['tracking_number'] or 'not yet assigned'}, "
        f"order_date={order['order_date']}"
    )
