"""
Development settings for aigle project.

This file contains settings specific to the development environment.
"""

import os
from .base import *  # noqa: F403, F401
from .base import SQL_ECHO
import builtins

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
            "level": "DEBUG" if SQL_ECHO else "WARNING",
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

# custom dev / debug utils


def get_raw_sql(queryset):
    from django.db import connection

    try:
        compiler = queryset.query.get_compiler(using=connection.alias)
        sql, params = compiler.as_sql()
        cursor = connection.cursor()
        if hasattr(cursor, "mogrify"):
            return cursor.mogrify(sql, params).decode("utf-8")
        else:
            formatted_sql = sql
            for param in params:
                if isinstance(param, str):
                    formatted_sql = formatted_sql.replace("%s", f"'{param}'", 1)
                elif param is None:
                    formatted_sql = formatted_sql.replace("%s", "NULL", 1)
                else:
                    formatted_sql = formatted_sql.replace("%s", str(param), 1)
            return formatted_sql
    except Exception as e:
        return f"Error getting SQL: {e}"


# make them available globally

builtins.get_raw_sql = get_raw_sql
