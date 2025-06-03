import logging
import os
import logging_loki


def setup_scaleway_logger():
    """
    Setup Scaleway Cockpit logger using Loki (only for production/staging)
    """
    environment = os.environ.get("ENVIRONMENT", "development")

    # Only use Scaleway logging in production/staging
    if environment in ["production", "staging"]:
        handler = logging_loki.LokiHandler(
            url="https://logs.cockpit.fr-par.scw.cloud/loki/api/v1/push",
            tags={"job": "django_api", "environment": environment},
            auth=(
                os.environ.get("SCW_SECRET_KEY"),
                os.environ.get("COCKPIT_TOKEN_SECRET_KEY"),
            ),
            version="1",
        )

        logger = logging.getLogger(f"django-api-{environment}")
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)

        return logger
    else:
        # For local development, just return a basic logger
        logger = logging.getLogger(f"django-api-{environment}")
        logger.setLevel(logging.DEBUG)
        return logger


scaleway_logger = setup_scaleway_logger()
