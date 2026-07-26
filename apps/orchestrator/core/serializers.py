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
            "created_at",
            "updated_at",
        ]


class QueryResponseSerializer(serializers.ModelSerializer):
    trace = serializers.SerializerMethodField()

    class Meta:
        model = ConversationLog
        fields = [
            "conversation_id",
            "query_text",
            "intent",
            "status",
            "final_response",
            "last_agent_name",
            "confidence_score",
            "was_escalated",
            "agents_involved",
            "created_at",
            "updated_at",
            "trace",
        ]

    def get_trace(self, obj):
        from core.redis_client import get_trace

        return get_trace(str(obj.conversation_id))
