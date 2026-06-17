import time
import uuid

from core.utils.logs_helpers import log_api_call


class RequestLoggingMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.id = str(uuid.uuid4())
        start_time = time.time()

        response = self.get_response(request)

        duration = time.time() - start_time

        log_api_call(
            endpoint=request.path,
            method=request.method,
            user=str(request.user) if hasattr(request, "user") else "Anonymous",
            ip=str(self.get_client_ip(request)),
            request_id=request.id,
            duration_ms=round(duration * 1000, 2),
            status_code=response.status_code,
        )

        return response

    def get_client_ip(self, request):
        x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
        if x_forwarded_for:
            ip = x_forwarded_for.split(",")[0]
        else:
            ip = request.META.get("REMOTE_ADDR")
        return ip
