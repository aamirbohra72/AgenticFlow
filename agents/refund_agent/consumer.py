import logging
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import common.env  # noqa: F401
from common.messaging import start_consumer
from crew import run_refund_crew

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

QUEUE_NAME = "refund.tasks"
AGENT_NAME = "refund_agent"


def handle_task(task: dict) -> tuple[dict, float, str]:
    result_payload, confidence = run_refund_crew(
        task.get("query_text", ""),
        task.get("order_id"),
    )
    return result_payload, confidence, AGENT_NAME


def main():
    logger.info("Starting %s consumer on %s", AGENT_NAME, QUEUE_NAME)
    start_consumer(QUEUE_NAME, handle_task)


if __name__ == "__main__":
    main()
