import os
from .base import *  # noqa: F403, F401
from .base import BASE_DIR  # noqa: F401

DEBUG = True
ALLOWED_HOSTS = ["*"]

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

EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"

STATIC_ROOT = os.path.join(BASE_DIR, "staticfiles_test")
MEDIA_ROOT = os.path.join(BASE_DIR, "media_test")
