import logging
from typing import Optional


def get_app_logger():
    return logging.getLogger("aigle")


def log_api_call(
    endpoint: str,
    method: str,
    user: str,
    ip: str,
    request_id: str,
    status_code: str,
    duration_ms: Optional[str] = None,
    **kwargs,
):
    """Log API calls"""
    logger = get_app_logger()
    logger.info(
        f"API call: {method} {endpoint}",
        extra={
            "endpoint": endpoint,
            "method": method,
            "user": user,
            "ip": ip,
            "request_id": request_id,
            "status_code": status_code,
            "duration_ms": duration_ms,
            **kwargs,
        },
    )


def log_command_event(command_name: str, info: str, **kwargs):
    logger = get_app_logger()
    logger.info(
        f"Command event: {command_name}",
        extra={
            "command_name": command_name,
            "category": "command",
            "info": info,
            **kwargs,
        },
    )
