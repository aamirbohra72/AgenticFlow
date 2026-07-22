import os
import sys

# Allow imports from agent dir and agents/common
sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import common.env  # noqa: F401
from crewai import Agent, Crew, LLM, Process, Task

from tools import get_order_status


def run_order_crew(query_text: str, order_id: str | None) -> dict:
    """Run the Order Status Specialist crew for a single query."""
    model = os.getenv("LITELLM_MODEL", "mistral/mistral-small-latest")
    llm = LLM(model=model, api_key=os.getenv("MISTRAL_API_KEY"))

    agent = Agent(
        role="Order Status Specialist",
        goal="Provide accurate order status and tracking information to customers",
        backstory=(
            "You are an expert at looking up order details in the fulfillment system. "
            "You always use the get_order_status tool to fetch real data before answering."
        ),
        tools=[get_order_status],
        llm=llm,
        verbose=True,
    )

    order_hint = order_id or "extract from the customer query"
    task = Task(
        description=(
            f"Customer query: {query_text}\n"
            f"Order ID to look up: {order_hint}\n"
            "Use the get_order_status tool to fetch order details, then write a clear "
            "customer-friendly summary including status and tracking number if available."
        ),
        expected_output="A concise customer-facing summary of the order status and tracking info.",
        agent=agent,
    )

    crew = Crew(agents=[agent], tasks=[task], process=Process.sequential, verbose=True)
    result = crew.kickoff()

    summary = str(result)
    return {
        "summary": summary,
        "order_id": order_id,
    }
