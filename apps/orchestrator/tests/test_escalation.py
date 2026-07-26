from core.escalation import should_escalate


def test_low_confidence_refund_escalates():
    result = {
        "agent_name": "refund_agent",
        "confidence_score": 0.4,
        "result_payload": {"replacement_proposed": False},
    }
    assert should_escalate(result) is True


def test_high_confidence_no_escalate():
    result = {
        "agent_name": "refund_agent",
        "confidence_score": 0.9,
        "result_payload": {"replacement_proposed": False, "inventory_status": {"in_stock": True}},
    }
    assert should_escalate(result) is False


def test_replacement_out_of_stock_escalates():
    result = {
        "agent_name": "refund_agent",
        "confidence_score": 0.5,
        "result_payload": {
            "replacement_proposed": True,
            "inventory_status": {"in_stock": False},
        },
    }
    assert should_escalate(result) is True


def test_order_agent_never_escalates_by_default():
    result = {
        "agent_name": "order_agent",
        "confidence_score": 0.2,
        "result_payload": {},
    }
    assert should_escalate(result) is False
