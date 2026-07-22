from crewai.tools import tool

from db import get_inventory_by_item_name


@tool("check_inventory")
def check_inventory(item_name: str) -> str:
    """Check stock levels and restock ETA for an item by name."""
    item = get_inventory_by_item_name(item_name)
    if not item:
        return f"No inventory record found for '{item_name}'."
    in_stock = item["quantity_available"] > 0
    eta = item["restock_eta"] or "unknown"
    return (
        f"Item: {item['item_name']}, quantity_available={item['quantity_available']}, "
        f"in_stock={in_stock}, restock_eta={eta}"
    )
