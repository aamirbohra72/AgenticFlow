from core.intent import classify_intent, extract_order_id


def test_order_intent_and_id():
    result = classify_intent("Where is my order #1234?")
    assert result.intent == "order"
    assert result.order_id == "1234"


def test_inventory_intent():
    result = classify_intent("Are Wireless Headphones in stock?")
    assert result.intent == "inventory"


def test_refund_intent():
    result = classify_intent("I want a refund for order #5678, item was defective")
    assert result.intent == "refund"
    assert result.order_id == "5678"


def test_extract_order_id():
    assert extract_order_id("order 9999 please") == "9999"
