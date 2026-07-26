"""Request ID middleware for distributed tracing across API + agent logs."""

from __future__ import annotations

import logging
import uuid

logger = logging.getLogger(__name__)

REQUEST_ID_HEADER = "HTTP_X_REQUEST_ID"
RESPONSE_HEADER = "X-Request-ID"


class RequestIDMiddleware:
    """
    Ensure every request has an X-Request-ID.
    Attach it to request.request_id and echo it on the response.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request_id = request.META.get(REQUEST_ID_HEADER) or str(uuid.uuid4())
        request.request_id = request_id
        response = self.get_response(request)
        response[RESPONSE_HEADER] = request_id
        return response
