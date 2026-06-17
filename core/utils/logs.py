import logging
import os
import logging_loki


def setup_scaleway_logger():
    """Loki handler is only wired up for production/preprod."""
    environment = os.environ.get("ENVIRONMENT", "development")

    if environment in ["production", "preprod"]:
        handler = logging_loki.LokiHandler(
            url=os.environ.get("SCW_COCKPIT_URL"),
            tags={"job": "django_api", "environment": environment},
            auth=(
                os.environ.get("SCW_SECRET_KEY"),
                os.environ.get("SCW_COCKPIT_TOKEN_SECRET_KEY"),
            ),
            version="1",
        )

        logger = logging.getLogger(f"django-api-{environment}")
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)

        return logger
    else:
        logger = logging.getLogger(f"django-api-{environment}")
        logger.setLevel(logging.DEBUG)
        return logger


scaleway_logger = setup_scaleway_logger()
