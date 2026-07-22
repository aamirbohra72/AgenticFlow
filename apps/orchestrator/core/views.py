import logging

from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from core.escalation import build_escalation_payload, should_escalate
from core.intent import classify_intent
from core.models import ConversationLog
from core.rabbitmq_client import (
    QUEUE_MAP,
    publish_task,
    register_result_waiter,
    unregister_result_waiter,
    wait_for_result,
)
from core.serializers import QueryRequestSerializer, QueryResponseSerializer

logger = logging.getLogger(__name__)

RESULT_TIMEOUT = 30.0


def _format_response(result: dict) -> str:
    payload = result.get("result_payload", {})
    if isinstance(payload.get("summary"), str):
        return payload["summary"]
    if isinstance(payload.get("final_response"), str):
        return payload["final_response"]
    if isinstance(payload.get("message"), str):
        return payload["message"]
    return str(payload)


class IndexView(APIView):
    """GET / — service info and available endpoints."""

    def get(self, request):
        return Response(
            {
                "service": "Agentic Order Flow Orchestrator",
                "status": "ok",
                "endpoints": {
                    "query": {
                        "method": "POST",
                        "path": "/api/query/",
                        "body": {"query": "Where is my order #1234?"},
                    },
                    "admin": {"method": "GET", "path": "/admin/"},
                },
            }
        )


class QueryView(APIView):
    """
    POST /api/query/

    1. Log query to Postgres
    2. Classify intent (keyword-based)
    3. Publish task to RabbitMQ specialist queue
    4. Wait for agent result (with optional escalation)
    5. Return synthesized answer
    """

    def post(self, request):
        serializer = QueryRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        query_text = serializer.validated_data["query"]

        intent_result = classify_intent(query_text)

        log = ConversationLog.objects.create(
            query_text=query_text,
            intent=intent_result.intent,
            status=ConversationLog.Status.PENDING,
        )
        conversation_id = str(log.conversation_id)

        queue = QUEUE_MAP.get(intent_result.intent, QUEUE_MAP["order"])
        task_payload = {
            "conversation_id": conversation_id,
            "query_text": query_text,
            "order_id": intent_result.order_id,
            "intent": intent_result.intent,
            "context": {
                "item_name": intent_result.item_name,
            },
        }

        log.status = ConversationLog.Status.IN_PROGRESS
        log.save(update_fields=["status", "updated_at"])

        register_result_waiter(conversation_id)

        try:
            publish_task(queue, task_payload)
            result = wait_for_result(conversation_id, timeout=RESULT_TIMEOUT)
            agent_results = [result]

            # Escalation path
            if should_escalate(result, agent_results):
                log.status = ConversationLog.Status.ESCALATED
                log.save(update_fields=["status", "updated_at"])

                escalation_payload = build_escalation_payload(
                    conversation_id=conversation_id,
                    query_text=query_text,
                    order_id=intent_result.order_id,
                    agent_results=agent_results,
                )
                # Reset waiter so we block for the escalation agent's result
                unregister_result_waiter(conversation_id)
                register_result_waiter(conversation_id)
                publish_task(QUEUE_MAP["escalation"], escalation_payload)
                result = wait_for_result(
                    conversation_id,
                    timeout=RESULT_TIMEOUT,
                    agent_name="escalation_agent",
                )
                agent_results.append(result)

            final_response = _format_response(result)
            log.final_response = final_response
            log.status = ConversationLog.Status.RESOLVED
            log.updated_at = timezone.now()
            log.save(update_fields=["final_response", "status", "updated_at"])

            return Response(QueryResponseSerializer(log).data, status=status.HTTP_200_OK)

        except TimeoutError:
            log.status = ConversationLog.Status.PENDING
            log.save(update_fields=["status", "updated_at"])
            return Response(
                {"error": "Agent did not respond in time", "conversation_id": conversation_id},
                status=status.HTTP_504_GATEWAY_TIMEOUT,
            )
        except Exception as exc:
            logger.exception("Query processing failed for %s", conversation_id)
            return Response(
                {"error": str(exc), "conversation_id": conversation_id},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
        finally:
            unregister_result_waiter(conversation_id)
