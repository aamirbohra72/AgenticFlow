"""Refund eligibility unit tests (no LLM)."""

from datetime import date, timedelta
from unittest.mock import patch
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from eligibility import compute_eligibility  # noqa: E402


def test_no_order_id_low_confidence():
    payload, confidence = compute_eligibility(None)
    assert payload["eligible"] is False
    assert confidence < 0.6


@patch("eligibility.get_order_by_id")
@patch("eligibility.get_refund_policy")
@patch("eligibility.get_inventory_status")
def test_within_window_high_confidence(mock_inv, mock_policy, mock_order):
    mock_order.return_value = {
        "id": 5678,
        "item_name": "Running Shoes",
        "item_category": "apparel",
        "order_date": date.today() - timedelta(days=5),
        "status": "delivered",
    }
    mock_policy.return_value = {
        "item_category": "apparel",
        "refund_window_days": 14,
        "requires_manager_approval": False,
    }
    mock_inv.return_value = {"in_stock": True, "quantity_available": 3}

    payload, confidence = compute_eligibility("5678")
    assert payload["eligible"] is True
    assert confidence == 0.9
    assert payload["replacement_proposed"] is False


@patch("eligibility.get_order_by_id")
@patch("eligibility.get_refund_policy")
@patch("eligibility.get_inventory_status")
def test_outside_window_oos_triggers_escalation_flags(mock_inv, mock_policy, mock_order):
    mock_order.return_value = {
        "id": 3333,
        "item_name": "Running Shoes",
        "item_category": "apparel",
        "order_date": date.today() - timedelta(days=20),
        "status": "delivered",
    }
    mock_policy.return_value = {
        "item_category": "apparel",
        "refund_window_days": 14,
        "requires_manager_approval": False,
    }
    mock_inv.return_value = {"in_stock": False, "quantity_available": 0, "restock_eta": "2026-08-09"}

    payload, confidence = compute_eligibility("3333")
    assert payload["eligible"] is False
    assert payload["replacement_proposed"] is True
    assert confidence < 0.6
    assert payload["requires_escalation"] is True
