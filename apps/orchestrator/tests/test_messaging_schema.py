from core.rabbitmq_client import SCHEMA_VERSION, build_task_payload


def test_build_task_payload_has_v2_fields():
    payload = build_task_payload(
        conversation_id="abc-123",
        query_text="Where is my order #1234?",
        intent="order",
        order_id="1234",
    )
    assert payload["schema_version"] == SCHEMA_VERSION
    assert payload["conversation_id"] == "abc-123"
    assert payload["intent"] == "order"
    assert payload["order_id"] == "1234"
    assert payload["attempt"] == 1
    assert "correlation_id" in payload
    assert payload["correlation_id"].startswith("abc-123:")
    assert "timestamp" in payload
