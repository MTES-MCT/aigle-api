import os
from .base import *  # noqa: F403, F401
from .base import BASE_DIR, REST_FRAMEWORK  # noqa: F401

DEBUG = True
ALLOWED_HOSTS = ["*"]

# Disable DRF rate throttling in the test suite: it is order/timing dependent and would
# make otherwise-correct tests flaky. The throttle configuration is exercised against the
# running server instead.
REST_FRAMEWORK = {
    **REST_FRAMEWORK,
    "DEFAULT_THROTTLE_RATES": {"anon": None, "user": None, "login": None},
}

DATABASES = {
    "default": {
        "ENGINE": os.environ.get(
            "SQL_ENGINE", "django.contrib.gis.db.backends.postgis"
        ),
        "NAME": os.environ.get("SQL_DATABASE_TEST", "aigle-test"),
        "USER": os.environ.get("SQL_USER_TEST", os.environ.get("SQL_USER", "aigle")),
        "PASSWORD": os.environ.get(
            "SQL_PASSWORD_TEST", os.environ.get("SQL_PASSWORD", "")
        ),
        "HOST": os.environ.get(
            "SQL_HOST_TEST", os.environ.get("SQL_HOST", "localhost")
        ),
        "PORT": os.environ.get("SQL_PORT_TEST", os.environ.get("SQL_PORT", "5432")),
        "TEST": {
            "NAME": os.environ.get("SQL_DATABASE_TEST", "aigle-test"),
        },
    }
}

if os.environ.get("ENVIRONMENT") in ["development", "test"]:
    GDAL_LIBRARY_PATH = os.environ.get(
        "GDAL_LIBRARY_PATH", "/opt/homebrew/opt/gdal/lib/libgdal.dylib"
    )
    GEOS_LIBRARY_PATH = os.environ.get(
        "GEOS_LIBRARY_PATH", "/opt/homebrew/opt/geos/lib/libgeos_c.dylib"
    )

PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.MD5PasswordHasher",
]

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
        "level": "WARNING",
    },
    "loggers": {
        "django": {
            "handlers": ["console"],
            "level": "WARNING",
            "propagate": False,
        },
        "django.request": {
            "handlers": ["console"],
            "level": "CRITICAL",
            "propagate": False,
        },
        "django.db.backends": {
            "handlers": ["console"],
            "level": "ERROR",
            "propagate": False,
        },
    },
}

CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True

# Use an in-process cache for tests: CI has no Redis, and this keeps the cache
# independent of the dev Redis. A conftest autouse fixture clears it between tests
# (LocMemCache is not rolled back with the DB transaction).
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
    }
}

EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"

STATIC_ROOT = os.path.join(BASE_DIR, "staticfiles_test")
MEDIA_ROOT = os.path.join(BASE_DIR, "media_test")
