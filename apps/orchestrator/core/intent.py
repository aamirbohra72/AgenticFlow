"""Keyword-based intent classification (v1 — no LLM)."""

import re
from dataclasses import dataclass

REFUND_KEYWORDS = ("refund", "return", "defective", "damaged", "money back", "broken")
INVENTORY_KEYWORDS = ("stock", "available", "in stock", "restock", "inventory")
ORDER_KEYWORDS = ("where", "track", "status", "shipped", "delivered", "order")

ORDER_ID_PATTERN = re.compile(r"#?\s*(\d{3,})")


@dataclass
class IntentResult:
    intent: str
    order_id: str | None
    item_name: str | None


def extract_order_id(text: str) -> str | None:
    match = ORDER_ID_PATTERN.search(text)
    return match.group(1) if match else None


def extract_item_name(text: str) -> str | None:
    """Best-effort extraction of quoted or capitalized product names."""
    quoted = re.search(r'"([^"]+)"', text) or re.search(r"'([^']+)'", text)
    if quoted:
        return quoted.group(1)
    return None


def classify_intent(query_text: str) -> IntentResult:
    lower = query_text.lower()

    if any(kw in lower for kw in REFUND_KEYWORDS):
        intent = "refund"
    elif any(kw in lower for kw in INVENTORY_KEYWORDS):
        intent = "inventory"
    elif any(kw in lower for kw in ORDER_KEYWORDS):
        intent = "order"
    else:
        intent = "order"

    return IntentResult(
        intent=intent,
        order_id=extract_order_id(query_text),
        item_name=extract_item_name(query_text),
    )
