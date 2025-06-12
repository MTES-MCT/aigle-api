"""
Production settings for aigle project.

This file contains settings specific to production and preprod environments.
"""

import os
from .base import *  # noqa: F403, F401

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = False

# Production logging configuration
BASE_HANDLERS = ["console", "scaleway_loki"]

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "{levelname} {asctime} {module} {process:d} {thread:d} {message}",
            "style": "{",
        },
        "simple": {
            "format": "{levelname} {message}",
            "style": "{",
        },
        "colored": {
            "format": "{levelname} {asctime} {name} {message}",
            "style": "{",
        },
    },
    "filters": {
        "require_debug_true": {
            "()": "django.utils.log.RequireDebugTrue",
        }
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "verbose",
        },
        "scaleway_loki": {
            "class": "logging_loki.LokiHandler",
            "url": os.environ.get("SCW_COCKPIT_URL"),
            "tags": {
                "job": "django_api",
                "environment": ENVIRONMENT,  # noqa: F405
            },
            "auth": (
                os.environ.get("SCW_SECRET_KEY"),
                os.environ.get("SCW_COCKPIT_TOKEN_SECRET_KEY"),
            ),
            "version": "1",
        },
        "mail_admins": {
            "level": "ERROR",
            "class": "django.utils.log.AdminEmailHandler",
            "include_html": True,
        },
    },
    "root": {
        "handlers": BASE_HANDLERS,
        "level": "INFO",
    },
    "loggers": {
        "django": {
            "handlers": BASE_HANDLERS,
            "level": "INFO",
            "propagate": False,
        },
        "django.request": {
            "handlers": BASE_HANDLERS + ["mail_admins"],
            "level": "WARNING",
            "propagate": False,
        },
        "django.db.backends": {
            "handlers": BASE_HANDLERS,
            "level": "WARNING",
            "propagate": False,
        },
        "django.utils.autoreload": {
            "handlers": BASE_HANDLERS,
            "level": "WARNING",
            "propagate": False,
        },
        "django.server": {
            "handlers": BASE_HANDLERS,
            "level": "INFO",
            "propagate": False,
        },
        "django.template": {
            "handlers": BASE_HANDLERS,
            "level": "WARNING",
            "propagate": False,
        },
        "django.security": {
            "handlers": BASE_HANDLERS,
            "level": "INFO",
            "propagate": False,
        },
        "aigle": {
            "handlers": BASE_HANDLERS,
            "level": "DEBUG",
            "propagate": False,
        },
    },
}
