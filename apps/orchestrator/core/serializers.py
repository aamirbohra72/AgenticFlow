from rest_framework import serializers

from .models import ConversationLog


class QueryRequestSerializer(serializers.Serializer):
    query = serializers.CharField(max_length=2000)


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
            "created_at",
            "trace",
        ]

    def get_trace(self, obj):
        from core.redis_client import get_trace

        return get_trace(str(obj.conversation_id))
