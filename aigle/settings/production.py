"""
Production settings for aigle project.

This file contains settings specific to production and preprod environments.
"""

import os
from .base import *  # noqa: F403, F401
from .base import DOMAIN, SECRET_KEY

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = False

# Fail fast rather than boot production with the insecure development fallback key
# (which would make every signed value — JWTs, password-reset tokens — forgeable).
if not os.environ.get("DJANGO_SECRET_KEY") or SECRET_KEY.startswith("django-insecure-"):
    raise RuntimeError(
        "DJANGO_SECRET_KEY must be set to a strong, unique value in production."
    )

# ---------------------------------------------------------------------------
# HTTPS / transport security
# The app runs behind a TLS-terminating reverse proxy, so trust its forwarded
# protocol header and force everything onto HTTPS.
# ---------------------------------------------------------------------------
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = True

# HSTS: tell browsers to only ever use HTTPS for this host (1 year, incl. subdomains).
SECURE_HSTS_SECONDS = int(
    os.environ.get("SECURE_HSTS_SECONDS", str(60 * 60 * 24 * 365))
)
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True

# ---------------------------------------------------------------------------
# Cookies (Django admin / session / CSRF) — HTTPS-only, not JS-readable.
# ---------------------------------------------------------------------------
SESSION_COOKIE_SECURE = True
SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_SECURE = True

# ---------------------------------------------------------------------------
# Misc hardening headers.
# ---------------------------------------------------------------------------
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"

# ---------------------------------------------------------------------------
# CORS: restrict to the known frontends. Defaults to the configured DOMAIN; set
# CORS_ALLOWED_ORIGINS (comma-separated, full scheme+host) to list every origin that
# must reach the API (e.g. the internal app AND the public site).
# ---------------------------------------------------------------------------
CORS_ALLOW_ALL_ORIGINS = False
if os.environ.get("CORS_ALLOWED_ORIGINS"):
    CORS_ALLOWED_ORIGINS = os.environ.get("CORS_ALLOWED_ORIGINS").split(",")
elif DOMAIN:
    CORS_ALLOWED_ORIGINS = [f"https://{DOMAIN}"]

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
