import logging
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import common.env  # noqa: F401
from common.messaging import start_consumer
from crew import run_inventory_crew

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

QUEUE_NAME = "inventory.tasks"
AGENT_NAME = "inventory_agent"


def handle_task(task: dict) -> tuple[dict, float, str]:
    context = task.get("context") or {}
    item_name = context.get("item_name")
    if not item_name and task.get("query_text"):
        # Best effort: look for product-like phrases
        query = task["query_text"]
        for seed in ("Wireless Headphones", "Running Shoes", "Smart Watch", "Laptop Stand"):
            if seed.lower() in query.lower():
                item_name = seed
                break

    result_payload, confidence = run_inventory_crew(task.get("query_text", ""), item_name)
    return result_payload, confidence, AGENT_NAME


def main():
    logger.info("Starting %s consumer on %s", AGENT_NAME, QUEUE_NAME)
    start_consumer(QUEUE_NAME, handle_task)


if __name__ == "__main__":
    main()
