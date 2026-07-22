"""Upstash Redis client for live conversation trace snapshots."""

import json
import logging
import os
from datetime import datetime, timezone

from upstash_redis import Redis

logger = logging.getLogger(__name__)

_redis_client: Redis | None = None


def get_redis() -> Redis:
    global _redis_client
    if _redis_client is None:
        url = os.getenv("UPSTASH_REDIS_URL", "")
        token = os.getenv("UPSTASH_REDIS_TOKEN", "")
        if not url or not token:
            raise ValueError("UPSTASH_REDIS_URL and UPSTASH_REDIS_TOKEN are required")
        _redis_client = Redis(url=url, token=token)
    return _redis_client


def _trace_key(conversation_id: str) -> str:
    return f"trace:{conversation_id}"


def append_trace(conversation_id: str, agent: str, message: str) -> None:
    """Append a trace entry to the conversation's Redis list."""
    entry = {
        "agent": agent,
        "message": message,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    try:
        get_redis().rpush(_trace_key(conversation_id), json.dumps(entry))
    except Exception:
        logger.exception("Failed to append trace for %s", conversation_id)


def get_trace(conversation_id: str) -> list[dict]:
    """Return all trace entries for a conversation."""
    try:
        raw_entries = get_redis().lrange(_trace_key(conversation_id), 0, -1)
        return [json.loads(e) for e in raw_entries]
    except Exception:
        logger.exception("Failed to read trace for %s", conversation_id)
        return []
