import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import common.env  # noqa: F401
import autogen


def run_escalation_conversation(query_text: str, agent_results: list) -> str:
    """
    Run a short AutoGen conversation between CustomerIntent and PolicyResolver
    to synthesize a final recommended response from conflicting agent outputs.
    """
    api_key = os.getenv("MISTRAL_API_KEY")
    if not api_key:
        raise ValueError("MISTRAL_API_KEY is required for escalation agent")

    config_list = [
        {
            "model": "mistral-small-latest",
            "api_key": api_key,
            "base_url": "https://api.mistral.ai/v1",
        }
    ]

    llm_config = {
        "config_list": config_list,
        "temperature": 0.3,
        "timeout": 120,
    }

    context_summary = json.dumps(agent_results, indent=2, default=str)

    customer_proxy = autogen.UserProxyAgent(
        name="CustomerIntent",
        human_input_mode="NEVER",
        max_consecutive_auto_reply=2,
        is_termination_msg=lambda msg: "FINAL_RESPONSE:" in (msg.get("content") or ""),
        code_execution_config=False,
    )

    policy_resolver = autogen.AssistantAgent(
        name="PolicyResolver",
        llm_config=llm_config,
        system_message=(
            "You are a senior customer service policy resolver. "
            "You receive the customer's original query and outputs from specialist agents "
            "(refund, inventory, order). Resolve conflicts fairly and propose a clear action. "
            "End your final message with a line starting with FINAL_RESPONSE: followed by "
            "the customer-facing answer."
        ),
    )

    prompt = (
        f"Customer query: {query_text}\n\n"
        f"Specialist agent results:\n{context_summary}\n\n"
        "Discuss briefly (2-3 turns) and produce a final customer-facing resolution. "
        "The PolicyResolver must end with FINAL_RESPONSE: <answer>"
    )

    customer_proxy.initiate_chat(policy_resolver, message=prompt, max_turns=3)

    # Extract FINAL_RESPONSE from chat history
    for msg in reversed(policy_resolver.chat_messages.get(customer_proxy, [])):
        content = msg.get("content", "")
        if "FINAL_RESPONSE:" in content:
            return content.split("FINAL_RESPONSE:", 1)[1].strip()

    # Fallback to last assistant message
    for msg in reversed(policy_resolver.chat_messages.get(customer_proxy, [])):
        if msg.get("content"):
            return msg["content"]

    return "We are reviewing your case and will follow up shortly."
