import logging
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import common.env  # noqa: F401
from common.messaging import start_consumer
from crew import run_order_crew

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

QUEUE_NAME = "order.tasks"
AGENT_NAME = "order_agent"


def handle_task(task: dict) -> tuple[dict, float, str]:
    query_text = task.get("query_text", "")
    order_id = task.get("order_id")
    result_payload = run_order_crew(query_text, order_id)
    return result_payload, 0.9, AGENT_NAME


def main():
    logger.info("Starting %s consumer on %s", AGENT_NAME, QUEUE_NAME)
    start_consumer(QUEUE_NAME, handle_task)


if __name__ == "__main__":
    main()
