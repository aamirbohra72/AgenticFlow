import logging

from django.conf import settings
from django.db import connection
from django.shortcuts import get_object_or_404, render
from django.views.decorators.csrf import ensure_csrf_cookie
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from core.auth import APIKeyAuthentication, APIKeyRateThrottle, IsAPIKeyAuthenticated
from core.intent import classify_intent
from core.metrics import snapshot
from core.models import ConversationLog
from core.orchestration import run_conversation_pipeline
from core.rabbitmq_client import check_rabbitmq, result_consumer_alive
from core.redis_client import check_redis, clear_trace, get_trace
from core.serializers import (
    ConversationListSerializer,
    QueryRequestSerializer,
    QueryResponseSerializer,
)

logger = logging.getLogger(__name__)

PROTECTED = {
    "authentication_classes": [APIKeyAuthentication],
    "permission_classes": [IsAPIKeyAuthenticated],
    "throttle_classes": [APIKeyRateThrottle],
}


def _request_id(request) -> str:
    return getattr(request, "request_id", "") or ""


def _with_request_id(data: dict, request) -> dict:
    if isinstance(data, dict):
        data = {**data, "request_id": data.get("request_id") or _request_id(request)}
    return data


class IndexView(APIView):
    """GET / — service info and available endpoints."""

    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = []

    def get(self, request):
        return Response(
            {
                "service": "Agentic Order Flow Orchestrator",
                "status": "ok",
                "version": "2.0",
                "auth": "Send X-API-Key or Authorization: Api-Key <key> for /api/* (except /api/health/)",
                "endpoints": {
                    "dashboard": {"method": "GET", "path": "/dashboard/"},
                    "query": {
                        "method": "POST",
                        "path": "/api/query/",
                        "body": {"query": "Where is my order #1234?"},
                    },
                    "conversations": {"method": "GET", "path": "/api/conversations/"},
                    "metrics": {"method": "GET", "path": "/api/metrics/"},
                    "health": {"method": "GET", "path": "/api/health/"},
                    "admin": {"method": "GET", "path": "/admin/"},
                },
            }
        )


class HealthView(APIView):
    """GET /api/health/ — public liveness (no API key)."""

    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = []

    def get(self, request):
        checks = {}

        try:
            connection.ensure_connection()
            checks["postgres"] = {"ok": True, "detail": "connected"}
        except Exception as exc:
            checks["postgres"] = {"ok": False, "detail": str(exc)}

        checks["rabbitmq"] = check_rabbitmq()
        checks["redis"] = check_redis()
        checks["result_consumer"] = {
            "ok": bool(result_consumer_alive),
            "detail": "alive" if result_consumer_alive else "not_started",
        }

        healthy = all(c.get("ok") for c in checks.values())
        return Response(
            {
                "status": "healthy" if healthy else "degraded",
                "checks": checks,
                "request_id": _request_id(request),
            },
            status=status.HTTP_200_OK if healthy else status.HTTP_503_SERVICE_UNAVAILABLE,
        )


class MetricsView(APIView):
    """GET /api/metrics/ — counters and latency percentiles (API key required)."""

    authentication_classes = PROTECTED["authentication_classes"]
    permission_classes = PROTECTED["permission_classes"]
    throttle_classes = PROTECTED["throttle_classes"]

    def get(self, request):
        data = snapshot()
        data["request_id"] = _request_id(request)
        return Response(data)


class QueryView(APIView):
    """POST /api/query/ — main orchestration entrypoint (API key required)."""

    authentication_classes = PROTECTED["authentication_classes"]
    permission_classes = PROTECTED["permission_classes"]
    throttle_classes = PROTECTED["throttle_classes"]

    def post(self, request):
        serializer = QueryRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        query_text = serializer.validated_data["query"]
        request_id = _request_id(request)

        intent_result = classify_intent(query_text)
        log = ConversationLog.objects.create(
            query_text=query_text,
            intent=intent_result.intent,
            status=ConversationLog.Status.PENDING,
            request_id=request_id or "",
        )

        try:
            log = run_conversation_pipeline(log, request_id=request_id)
            return Response(
                _with_request_id(QueryResponseSerializer(log).data, request),
                status=status.HTTP_200_OK,
            )
        except TimeoutError:
            return Response(
                {
                    "error": "Agent did not respond in time",
                    "conversation_id": str(log.conversation_id),
                    "status": log.status,
                    "error_message": log.error_message,
                    "hint": "Check RabbitMQ, agent processes, and DLQ queues (*.dlq)",
                    "request_id": request_id,
                },
                status=status.HTTP_504_GATEWAY_TIMEOUT,
            )
        except Exception as exc:
            logger.exception("Query processing failed for %s", log.conversation_id)
            return Response(
                {
                    "error": str(exc),
                    "conversation_id": str(log.conversation_id),
                    "status": log.status,
                    "request_id": request_id,
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class ConversationListView(APIView):
    authentication_classes = PROTECTED["authentication_classes"]
    permission_classes = PROTECTED["permission_classes"]
    throttle_classes = PROTECTED["throttle_classes"]

    def get(self, request):
        limit = min(int(request.query_params.get("limit", 25)), 100)
        qs = ConversationLog.objects.all()[:limit]
        return Response(ConversationListSerializer(qs, many=True).data)


class ConversationDetailView(APIView):
    authentication_classes = PROTECTED["authentication_classes"]
    permission_classes = PROTECTED["permission_classes"]
    throttle_classes = PROTECTED["throttle_classes"]

    def get(self, request, conversation_id):
        log = get_object_or_404(ConversationLog, conversation_id=conversation_id)
        return Response(_with_request_id(QueryResponseSerializer(log).data, request))


class ConversationReprocessView(APIView):
    authentication_classes = PROTECTED["authentication_classes"]
    permission_classes = PROTECTED["permission_classes"]
    throttle_classes = PROTECTED["throttle_classes"]

    def post(self, request, conversation_id):
        log = get_object_or_404(ConversationLog, conversation_id=conversation_id)
        clear_trace(str(log.conversation_id))
        request_id = _request_id(request)

        try:
            log = run_conversation_pipeline(log, request_id=request_id)
            return Response(_with_request_id(QueryResponseSerializer(log).data, request))
        except TimeoutError:
            return Response(
                {
                    "error": "Agent did not respond in time",
                    "conversation_id": str(log.conversation_id),
                    "status": log.status,
                    "request_id": request_id,
                },
                status=status.HTTP_504_GATEWAY_TIMEOUT,
            )
        except Exception as exc:
            logger.exception("Reprocess failed for %s", conversation_id)
            return Response(
                {"error": str(exc), "conversation_id": str(log.conversation_id), "request_id": request_id},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class ConversationTraceView(APIView):
    authentication_classes = PROTECTED["authentication_classes"]
    permission_classes = PROTECTED["permission_classes"]
    throttle_classes = PROTECTED["throttle_classes"]

    def get(self, request, conversation_id):
        get_object_or_404(ConversationLog, conversation_id=conversation_id)
        return Response(
            {
                "conversation_id": str(conversation_id),
                "trace": get_trace(str(conversation_id)),
                "request_id": _request_id(request),
            }
        )


@ensure_csrf_cookie
def dashboard_view(request):
    """HTML playground — API key injected from server env for local demo."""
    return render(
        request,
        "dashboard.html",
        {
            "api_key": settings.API_KEY,
            "version": "2.0",
        },
    )
