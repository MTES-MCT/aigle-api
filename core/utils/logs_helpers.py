import logging


def get_app_logger():
    return logging.getLogger("aigle")


def log_user_action(user, action, **kwargs):
    logger = get_app_logger()
    logger.info(
        f"User action: {action}",
        extra={
            "user_id": user.id if hasattr(user, "id") else None,
            "username": str(user),
            "action": action,
            **kwargs,
        },
    )


def log_api_call(endpoint, method, status_code, duration=None, **kwargs):
    """Log API calls"""
    logger = get_app_logger()
    logger.info(
        f"API call: {method} {endpoint}",
        extra={
            "endpoint": endpoint,
            "method": method,
            "status_code": status_code,
            "duration_ms": duration,
            **kwargs,
        },
    )


def log_command_event(command_name, info, **kwargs):
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
