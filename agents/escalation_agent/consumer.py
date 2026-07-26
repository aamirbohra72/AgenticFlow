import logging
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import common.env  # noqa: F401
from autogen_config import run_escalation_conversation
from common.messaging import start_consumer

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

QUEUE_NAME = "escalation.tasks.v2"
AGENT_NAME = "escalation_agent"


def handle_task(task: dict) -> tuple[dict, float, str]:
    context = task.get("context") or {}
    agent_results = context.get("agent_results", [])
    final_response = run_escalation_conversation(
        task.get("query_text", ""),
        agent_results,
    )
    return {"final_response": final_response, "summary": final_response}, 1.0, AGENT_NAME


def main():
    logger.info("Starting %s consumer on %s", AGENT_NAME, QUEUE_NAME)
    start_consumer(QUEUE_NAME, handle_task)


if __name__ == "__main__":
    main()
