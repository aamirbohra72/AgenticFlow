import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import common.env  # noqa: F401
from crewai import Agent, Crew, LLM, Process, Task

from db import get_inventory_status, get_order_by_id, get_refund_policy
from tools import lookup_refund_eligibility


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
    replacement_proposed = not within_window and inventory["in_stock"]

    if within_window and not policy["requires_manager_approval"]:
        eligible, confidence, reason = True, 0.9, "Within refund window, no manager approval needed"
    elif within_window and policy["requires_manager_approval"]:
        eligible, confidence, reason = True, 0.7, "Within window but requires manager approval"
    elif replacement_proposed:
        eligible, confidence, reason = False, 0.5, "Outside window; replacement offered instead of refund"
    else:
        eligible, confidence, reason = False, 0.4, "Outside refund window and no replacement available"

    return {
        "eligible": eligible,
        "reason": reason,
        "replacement_proposed": replacement_proposed,
        "requires_escalation": confidence < 0.6 or (replacement_proposed and not inventory["in_stock"]),
        "inventory_status": inventory,
        "order_id": order_id,
        "item_name": order["item_name"],
    }, confidence


def run_refund_crew(query_text: str, order_id: str | None) -> tuple[dict, float]:
    model = os.getenv("LITELLM_MODEL", "mistral/mistral-small-latest")
    llm = LLM(model=model, api_key=os.getenv("MISTRAL_API_KEY"))

    agent = Agent(
        role="Refund Policy Specialist",
        goal="Determine refund eligibility and explain policy clearly to customers",
        backstory=(
            "You are a refund policy expert who always checks order details and policy rules "
            "using the lookup_refund_eligibility tool before making recommendations."
        ),
        tools=[lookup_refund_eligibility],
        llm=llm,
        verbose=True,
    )

    order_hint = order_id or "extract from query"
    task = Task(
        description=(
            f"Customer query: {query_text}\n"
            f"Order ID: {order_hint}\n"
            "Use lookup_refund_eligibility, then explain whether a refund or replacement is appropriate."
        ),
        expected_output="Clear refund eligibility explanation with next steps for the customer.",
        agent=agent,
    )

    crew = Crew(agents=[agent], tasks=[task], process=Process.sequential, verbose=True)
    summary = str(crew.kickoff())

    payload, confidence = compute_eligibility(order_id)
    payload["summary"] = summary
    return payload, confidence
