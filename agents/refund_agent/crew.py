import logging
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import common.env  # noqa: F401
from crewai import Agent, Crew, LLM, Process, Task

from eligibility import compute_eligibility
from tools import lookup_refund_eligibility

logger = logging.getLogger(__name__)


def run_refund_crew(query_text: str, order_id: str | None) -> tuple[dict, float]:
    payload, confidence = compute_eligibility(order_id)

    # Prefer a short CrewAI narrative; fall back to deterministic summary on LLM errors/rate limits
    try:
        model = os.getenv("LITELLM_MODEL", "mistral/mistral-small-latest")
        llm = LLM(model=model, api_key=os.getenv("MISTRAL_API_KEY"))

        agent = Agent(
            role="Refund Policy Specialist",
            goal="Determine refund eligibility and explain policy clearly to customers",
            backstory=(
                "You are a refund policy expert who always checks order details and policy rules "
                "using the lookup_refund_eligibility tool before making recommendations. "
                "Call the tool once, then answer immediately."
            ),
            tools=[lookup_refund_eligibility],
            llm=llm,
            verbose=True,
            max_iter=2,
            allow_delegation=False,
        )

        order_hint = order_id or "extract from query"
        task = Task(
            description=(
                f"Customer query: {query_text}\n"
                f"Order ID: {order_hint}\n"
                "Use lookup_refund_eligibility once, then write a short customer-facing explanation."
            ),
            expected_output="Clear refund eligibility explanation with next steps for the customer.",
            agent=agent,
        )

        crew = Crew(
            agents=[agent],
            tasks=[task],
            process=Process.sequential,
            verbose=True,
            tracing=False,
        )
        payload["summary"] = str(crew.kickoff())
    except Exception:
        logger.exception("CrewAI refund summary failed; using deterministic summary")

    return payload, confidence
