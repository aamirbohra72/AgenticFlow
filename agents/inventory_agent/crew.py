import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import common.env  # noqa: F401
from crewai import Agent, Crew, LLM, Process, Task

from db import get_inventory_by_item_name
from tools import check_inventory


def run_inventory_crew(query_text: str, item_name: str | None) -> tuple[dict, float]:
    model = os.getenv("LITELLM_MODEL", "mistral/mistral-small-latest")
    llm = LLM(model=model, api_key=os.getenv("MISTRAL_API_KEY"))

    agent = Agent(
        role="Inventory Specialist",
        goal="Provide accurate stock availability and restock information",
        backstory=(
            "You are an inventory expert who always checks the database before answering "
            "questions about product availability."
        ),
        tools=[check_inventory],
        llm=llm,
        verbose=True,
        max_iter=3,
        allow_delegation=False,
    )

    item_hint = item_name or "infer from the customer query"
    task = Task(
        description=(
            f"Customer query: {query_text}\n"
            f"Item to check: {item_hint}\n"
            "Use check_inventory to look up stock, then summarize availability for the customer."
        ),
        expected_output="A concise summary of inventory status including in-stock status and restock ETA.",
        agent=agent,
    )

    crew = Crew(
        agents=[agent],
        tasks=[task],
        process=Process.sequential,
        verbose=True,
        tracing=False,
    )
    summary = str(crew.kickoff())

    # Compute structured payload and confidence from DB
    db_item = get_inventory_by_item_name(item_name) if item_name else None
    if not db_item and item_name:
        # Try fuzzy: extract from query words
        for word in query_text.split():
            if len(word) > 4:
                db_item = get_inventory_by_item_name(word)
                if db_item:
                    break

    if db_item:
        in_stock = db_item["quantity_available"] > 0
        confidence = 0.95
        payload = {
            "item_name": db_item["item_name"],
            "quantity_available": db_item["quantity_available"],
            "in_stock": in_stock,
            "restock_eta": str(db_item["restock_eta"]) if db_item["restock_eta"] else None,
            "summary": summary,
        }
    else:
        confidence = 0.5
        payload = {
            "item_name": item_name,
            "quantity_available": 0,
            "in_stock": False,
            "restock_eta": None,
            "summary": summary,
        }

    return payload, confidence
