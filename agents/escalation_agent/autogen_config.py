import json
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import common.env  # noqa: F401
import autogen
from openai import OpenAI

logger = logging.getLogger(__name__)


def _deterministic_resolution(query_text: str, agent_results: list) -> str:
    """Fallback when AutoGen/LLM cannot complete — still produces a clear decision."""
    refund = next((r for r in agent_results if r.get("agent_name") == "refund_agent"), {})
    inventory = next((r for r in agent_results if r.get("agent_name") == "inventory_agent"), {})
    refund_payload = refund.get("result_payload") or {}
    inv_payload = inventory.get("result_payload") or refund_payload.get("inventory_status") or {}

    reason = refund_payload.get("reason", "policy conflict")
    in_stock = inv_payload.get("in_stock")
    restock = inv_payload.get("restock_eta")
    item = refund_payload.get("item_name") or inv_payload.get("item_name") or "the item"

    if refund_payload.get("replacement_proposed") and in_stock is False:
        return (
            f"After reviewing your request ({query_text}), our escalation team found a conflict: "
            f"{reason}. {item} is currently out of stock"
            + (f" (restock ETA {restock})" if restock else "")
            + ". We recommend issuing a full refund to your original payment method, "
            "or offering store credit plus a courtesy discount on a future purchase. "
            "A specialist will finalize the refund within 1 business day."
        )

    if refund.get("confidence_score", 1) < 0.6:
        return (
            f"Your case required manager review because confidence was low ({reason}). "
            "We will approve a goodwill refund and email confirmation shortly."
        )

    return (
        f"Escalation review complete for: {query_text}. "
        f"Recommended action based on specialist findings: {reason}."
    )


def _mistral_single_shot(query_text: str, agent_results: list) -> str | None:
    """Single Mistral completion without AutoGen message `name` fields (Mistral rejects those)."""
    api_key = os.getenv("MISTRAL_API_KEY")
    if not api_key:
        return None

    client = OpenAI(api_key=api_key, base_url="https://api.mistral.ai/v1")
    context_summary = json.dumps(agent_results, indent=2, default=str)
    prompt = (
        "You are a senior customer service policy resolver.\n"
        f"Customer query: {query_text}\n\n"
        f"Specialist agent results:\n{context_summary}\n\n"
        "Resolve the conflict fairly in 2-4 sentences. "
        "Start your answer with FINAL_RESPONSE: "
    )
    try:
        response = client.chat.completions.create(
            model="mistral-small-latest",
            messages=[
                {"role": "system", "content": "You resolve refund/inventory conflicts for customers."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.3,
            max_tokens=400,
        )
        content = response.choices[0].message.content or ""
        if "FINAL_RESPONSE:" in content:
            return content.split("FINAL_RESPONSE:", 1)[1].strip()
        return content.strip() or None
    except Exception:
        logger.exception("Mistral single-shot escalation failed")
        return None


def run_escalation_conversation(query_text: str, agent_results: list) -> str:
    """
    Run a short AutoGen conversation between CustomerIntent and PolicyResolver.
    Falls back to a single Mistral call (no message names) or a deterministic resolution
    if AutoGen fails — Mistral's API rejects AutoGen's per-message `name` field (HTTP 422).
    """
    api_key = os.getenv("MISTRAL_API_KEY")
    if not api_key:
        raise ValueError("MISTRAL_API_KEY is required for escalation agent")

    config_list = [
        {
            "model": "mistral-small-latest",
            "api_key": api_key,
            "base_url": "https://api.mistral.ai/v1",
            "price": [0.0, 0.0],
        }
    ]

    llm_config = {
        "config_list": config_list,
        "temperature": 0.3,
        "timeout": 60,
    }

    context_summary = json.dumps(agent_results, indent=2, default=str)

    try:
        customer_proxy = autogen.UserProxyAgent(
            name="CustomerIntent",
            human_input_mode="NEVER",
            max_consecutive_auto_reply=1,
            is_termination_msg=lambda msg: "FINAL_RESPONSE:" in (msg.get("content") or ""),
            code_execution_config=False,
        )

        policy_resolver = autogen.AssistantAgent(
            name="PolicyResolver",
            llm_config=llm_config,
            system_message=(
                "You are a senior customer service policy resolver. "
                "Resolve conflicts between refund and inventory findings. "
                "End with FINAL_RESPONSE: followed by the customer-facing answer."
            ),
        )

        prompt = (
            f"Customer query: {query_text}\n\n"
            f"Specialist agent results:\n{context_summary}\n\n"
            "Produce a final customer-facing resolution. "
            "End with FINAL_RESPONSE: <answer>"
        )

        customer_proxy.initiate_chat(policy_resolver, message=prompt, max_turns=2)

        for msg in reversed(policy_resolver.chat_messages.get(customer_proxy, [])):
            content = msg.get("content", "")
            if "FINAL_RESPONSE:" in content:
                return content.split("FINAL_RESPONSE:", 1)[1].strip()

        for msg in reversed(policy_resolver.chat_messages.get(customer_proxy, [])):
            if msg.get("content"):
                return msg["content"]
    except Exception:
        logger.exception("AutoGen escalation chat failed; trying Mistral single-shot fallback")

    single = _mistral_single_shot(query_text, agent_results)
    if single:
        return single

    return _deterministic_resolution(query_text, agent_results)
