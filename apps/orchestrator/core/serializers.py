from rest_framework import serializers

from .models import ConversationLog


class QueryRequestSerializer(serializers.Serializer):
    query = serializers.CharField(max_length=2000)


class ConversationListSerializer(serializers.ModelSerializer):
    class Meta:
        model = ConversationLog
        fields = [
            "conversation_id",
            "query_text",
            "intent",
            "status",
            "last_agent_name",
            "confidence_score",
            "was_escalated",
            "agents_involved",
            "error_message",
            "request_id",
            "created_at",
            "updated_at",
        ]


class QueryResponseSerializer(serializers.ModelSerializer):
    trace = serializers.SerializerMethodField()
    latency_ms = serializers.SerializerMethodField()

    class Meta:
        model = ConversationLog
        fields = [
            "conversation_id",
            "query_text",
            "intent",
            "status",
            "final_response",
            "error_message",
            "last_agent_name",
            "confidence_score",
            "was_escalated",
            "agents_involved",
            "request_id",
            "created_at",
            "updated_at",
            "latency_ms",
            "trace",
        ]

    def get_trace(self, obj):
        from core.redis_client import get_trace

        return get_trace(str(obj.conversation_id))

    def get_latency_ms(self, obj):
        if not obj.created_at or not obj.updated_at:
            return None
        return int((obj.updated_at - obj.created_at).total_seconds() * 1000)
