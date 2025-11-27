"""
Test settings for aigle project.

This file contains settings specific to running tests.
It uses a separate test database configured via environment variables:
- SQL_ENGINE_TEST
- SQL_DATABASE_TEST
- SQL_USER_TEST
- SQL_PASSWORD_TEST
- SQL_HOST_TEST
- SQL_PORT_TEST

The test database must exist and will be cleaned before and after tests.
"""

import os
from .base import *  # noqa: F403, F401
from .base import BASE_DIR  # noqa: F401

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = True

# Test database configuration
# Uses separate environment variables for test database
# Falls back to regular database env vars if test vars not set
DATABASES = {
    "default": {
        "ENGINE": os.environ.get(
            "SQL_ENGINE_TEST", "django.contrib.gis.db.backends.postgis"
        ),
        "NAME": os.environ.get("SQL_DATABASE_TEST", "aigle"),
        "USER": os.environ.get(
            "SQL_USER_TEST", os.environ.get("SQL_USER", "aigle_user")
        ),
        "PASSWORD": os.environ.get(
            "SQL_PASSWORD_TEST", os.environ.get("SQL_PASSWORD", "aigle_password")
        ),
        "HOST": os.environ.get(
            "SQL_HOST_TEST", os.environ.get("SQL_HOST", "localhost")
        ),
        "PORT": os.environ.get("SQL_PORT_TEST", os.environ.get("SQL_PORT", "5432")),
        "TEST": {
            # Use the same database for tests (remote database, can't create new ones)
            "NAME": os.environ.get("SQL_DATABASE_TEST", "aigle"),
        },
    }
}

# GDAL/GEOS paths for macOS (if needed for tests)
if os.environ.get("ENVIRONMENT") in ["development", "test"]:
    GDAL_LIBRARY_PATH = os.environ.get(
        "GDAL_LIBRARY_PATH", "/opt/homebrew/opt/gdal/lib/libgdal.dylib"
    )
    GEOS_LIBRARY_PATH = os.environ.get(
        "GEOS_LIBRARY_PATH", "/opt/homebrew/opt/geos/lib/libgeos_c.dylib"
    )

# Speed up password hashing in tests
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.MD5PasswordHasher",
]

# Simplified logging for tests
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
        },
    },
    "root": {
        "handlers": ["console"],
        "level": "WARNING",  # Only show warnings and errors during tests
    },
    "loggers": {
        "django": {
            "handlers": ["console"],
            "level": "WARNING",
            "propagate": False,
        },
        "django.db.backends": {
            "handlers": ["console"],
            "level": "ERROR",  # Only show SQL errors
            "propagate": False,
        },
    },
}

# Celery configuration for tests - use eager mode (synchronous)
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True

# Email backend for tests
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"

# Static files
STATIC_ROOT = os.path.join(BASE_DIR, "staticfiles_test")

# Media files
MEDIA_ROOT = os.path.join(BASE_DIR, "media_test")
