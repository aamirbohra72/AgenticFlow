import logging

from django.db import connection
from django.shortcuts import get_object_or_404, render
from django.views.decorators.csrf import ensure_csrf_cookie
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from core.intent import classify_intent
from core.models import ConversationLog
from core.orchestration import run_conversation_pipeline
from core.rabbitmq_client import check_rabbitmq
from core.redis_client import check_redis, clear_trace, get_trace
from core.serializers import (
    ConversationListSerializer,
    QueryRequestSerializer,
    QueryResponseSerializer,
)

logger = logging.getLogger(__name__)


class IndexView(APIView):
    """GET / — service info and available endpoints."""

    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request):
        return Response(
            {
                "service": "Agentic Order Flow Orchestrator",
                "status": "ok",
                "version": "1.5",
                "endpoints": {
                    "dashboard": {"method": "GET", "path": "/dashboard/"},
                    "query": {
                        "method": "POST",
                        "path": "/api/query/",
                        "body": {"query": "Where is my order #1234?"},
                    },
                    "conversations": {"method": "GET", "path": "/api/conversations/"},
                    "conversation_detail": {
                        "method": "GET",
                        "path": "/api/conversations/{conversation_id}/",
                    },
                    "reprocess": {
                        "method": "POST",
                        "path": "/api/conversations/{conversation_id}/reprocess/",
                    },
                    "health": {"method": "GET", "path": "/api/health/"},
                    "admin": {"method": "GET", "path": "/admin/"},
                },
            }
        )


class HealthView(APIView):
    """GET /api/health/ — Postgres, RabbitMQ, Redis connectivity."""

    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request):
        checks = {}

        try:
            connection.ensure_connection()
            checks["postgres"] = {"ok": True, "detail": "connected"}
        except Exception as exc:
            checks["postgres"] = {"ok": False, "detail": str(exc)}

        checks["rabbitmq"] = check_rabbitmq()
        checks["redis"] = check_redis()

        healthy = all(c.get("ok") for c in checks.values())
        return Response(
            {"status": "healthy" if healthy else "degraded", "checks": checks},
            status=status.HTTP_200_OK if healthy else status.HTTP_503_SERVICE_UNAVAILABLE,
        )


class QueryView(APIView):
    """
    POST /api/query/

    1. Log query to Postgres
    2. Classify intent (keyword-based)
    3. Publish task to RabbitMQ specialist queue
    4. Optional refund → inventory fan-out
    5. Optional escalation (AutoGen)
    6. Return synthesized answer + trace
    """

    authentication_classes = []
    permission_classes = [AllowAny]

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

        try:
            log = run_conversation_pipeline(log)
            return Response(QueryResponseSerializer(log).data, status=status.HTTP_200_OK)
        except TimeoutError:
            log.status = ConversationLog.Status.PENDING
            log.save(update_fields=["status", "updated_at"])
            return Response(
                {
                    "error": "Agent did not respond in time",
                    "conversation_id": str(log.conversation_id),
                    "hint": "Check RabbitMQ and that the matching Flask agent is running",
                },
                status=status.HTTP_504_GATEWAY_TIMEOUT,
            )
        except Exception as exc:
            logger.exception("Query processing failed for %s", log.conversation_id)
            return Response(
                {"error": str(exc), "conversation_id": str(log.conversation_id)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class ConversationListView(APIView):
    """GET /api/conversations/ — recent conversations (no Redis trace)."""

    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request):
        limit = min(int(request.query_params.get("limit", 25)), 100)
        qs = ConversationLog.objects.all()[:limit]
        return Response(ConversationListSerializer(qs, many=True).data)


class ConversationDetailView(APIView):
    """GET /api/conversations/{conversation_id}/ — full detail + Redis trace."""

    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request, conversation_id):
        log = get_object_or_404(ConversationLog, conversation_id=conversation_id)
        return Response(QueryResponseSerializer(log).data)


class ConversationReprocessView(APIView):
    """POST /api/conversations/{conversation_id}/reprocess/ — replay the same query."""

    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request, conversation_id):
        log = get_object_or_404(ConversationLog, conversation_id=conversation_id)
        clear_trace(str(log.conversation_id))

        try:
            log = run_conversation_pipeline(log)
            return Response(QueryResponseSerializer(log).data, status=status.HTTP_200_OK)
        except TimeoutError:
            log.status = ConversationLog.Status.PENDING
            log.save(update_fields=["status", "updated_at"])
            return Response(
                {
                    "error": "Agent did not respond in time",
                    "conversation_id": str(log.conversation_id),
                },
                status=status.HTTP_504_GATEWAY_TIMEOUT,
            )
        except Exception as exc:
            logger.exception("Reprocess failed for %s", conversation_id)
            return Response(
                {"error": str(exc), "conversation_id": str(log.conversation_id)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class ConversationTraceView(APIView):
    """GET /api/conversations/{conversation_id}/trace/ — Redis-only live trace."""

    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request, conversation_id):
        get_object_or_404(ConversationLog, conversation_id=conversation_id)
        return Response(
            {
                "conversation_id": str(conversation_id),
                "trace": get_trace(str(conversation_id)),
            }
        )


@ensure_csrf_cookie
def dashboard_view(request):
    """Simple HTML playground + live conversation browser."""
    return render(request, "dashboard.html")
