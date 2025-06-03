import logging
import time
import uuid

logger = logging.getLogger("aigle")  # Replace 'myapp' with your app name


class RequestLoggingMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Generate request ID and start time
        request.id = str(uuid.uuid4())
        start_time = time.time()

        # Log incoming request
        logger.info(
            f"Request {request.method} {request.path}",
            extra={
                "request_id": request.id,
                "method": request.method,
                "path": request.path,
                "user": str(request.user) if hasattr(request, "user") else "Anonymous",
                "ip": self.get_client_ip(request),
            },
        )

        response = self.get_response(request)

        # Log response
        duration = time.time() - start_time
        logger.info(
            f"Response {response.status_code}",
            extra={
                "request_id": request.id,
                "status_code": response.status_code,
                "duration_ms": round(duration * 1000, 2),
            },
        )

        return response

    def get_client_ip(self, request):
        x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
        if x_forwarded_for:
            ip = x_forwarded_for.split(",")[0]
        else:
            ip = request.META.get("REMOTE_ADDR")
        return ip
