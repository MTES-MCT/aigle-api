"""
Development settings for aigle project.

This file contains settings specific to the development environment.
"""

import os
from .base import *  # noqa: F403, F401

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = True

# Development-specific GDAL/GEOS paths for macOS
if os.environ.get("ENVIRONMENT") == "development":
    GDAL_LIBRARY_PATH = os.environ.get(
        "GDAL_LIBRARY_PATH", "/opt/homebrew/opt/gdal/lib/libgdal.dylib"
    )
    GEOS_LIBRARY_PATH = os.environ.get(
        "GEOS_LIBRARY_PATH", "/opt/homebrew/opt/geos/lib/libgeos_c.dylib"
    )

# Debug toolbar configuration
INTERNAL_IPS = [
    "127.0.0.1",
]

# Development logging configuration
BASE_HANDLERS = ["console"]

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
            "()": "colorlog.ColoredFormatter",
            "format": "{log_color}{levelname} {asctime} {name} {message}",
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
            "formatter": "colored",
        },
    },
    "root": {
        "handlers": BASE_HANDLERS,
        "level": "DEBUG",
    },
    "loggers": {
        "django": {
            "handlers": BASE_HANDLERS,
            "level": "INFO",  # Keep at INFO even in development
            "propagate": False,
        },
        "django.request": {
            "handlers": BASE_HANDLERS,
            "level": "DEBUG",
            "propagate": False,
        },
        "django.db.backends": {
            "handlers": BASE_HANDLERS,
            "level": "WARNING",
            "propagate": False,
        },
        # Silence noisy Django loggers in development
        "django.utils.autoreload": {
            "handlers": BASE_HANDLERS,
            "level": "WARNING",  # Only show warnings/errors from autoreload
            "propagate": False,
        },
        "django.server": {
            "handlers": BASE_HANDLERS,
            "level": "INFO",  # Keep server logs but not debug
            "propagate": False,
        },
        "django.template": {
            "handlers": BASE_HANDLERS,
            "level": "WARNING",  # Silence template debug logs
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
