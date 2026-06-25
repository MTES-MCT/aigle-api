"""
Base Django settings for aigle project.

This file contains settings that are common across all environments.
Environment-specific settings inherit from this file.
"""

from datetime import timedelta, datetime
import os
from pathlib import Path

from core.utils.parsing import strtobool

import logging  # noqa: F401
import logging_loki  # noqa: F401
from core.utils.logs import scaleway_logger  # noqa: F401

from celery import Celery  # noqa: F401

DEPLOYMENT_DATETIME = datetime.now()

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent.parent

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = os.environ.get(
    "DJANGO_SECRET_KEY",
    "django-insecure-tz2s%wy_1typ8a6nh=(a51f64uknqo__79+0c^zi&y3q@b1!4$",
)

SQL_ECHO = strtobool(os.environ.get("SQL_ECHO", "false"))
ENVIRONMENT = os.environ.get("ENVIRONMENT", "development")

ALLOWED_HOSTS = []
if os.environ.get("ALLOWED_HOSTS"):
    ALLOWED_HOSTS = os.environ.get("ALLOWED_HOSTS").split(",")

# Application definition
DOMAIN = os.environ.get("DOMAIN")
SITE_NAME = os.environ.get("SITE_NAME", "Aigle")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.postgres",
    "corsheaders",
    "rest_framework",
    "rest_framework_gis",
    "rest_framework_api_key",
    "core",
    "djoser",
    "django_filters",
    "simple_history",
]

EMAIL_BACKEND = os.environ.get("EMAIL_BACKEND")
EMAIL_HOST = os.environ.get("EMAIL_HOST")
EMAIL_PORT = os.environ.get("EMAIL_PORT")
EMAIL_USE_TLS = os.environ.get("EMAIL_USE_TLS")
EMAIL_HOST_USER = os.environ.get("EMAIL_HOST_USER")
EMAIL_HOST_PASSWORD = os.environ.get("EMAIL_HOST_PASSWORD")
DEFAULT_FROM_EMAIL = os.environ.get("DEFAULT_FROM_EMAIL")

DJOSER = {
    "PASSWORD_RESET_CONFIRM_URL": "reset-password/{uid}/{token}",
    "LOGIN_FIELD": "email",
    "SERIALIZERS": {
        "current_user": "core.serializers.user.UserSerializer",
        "token_create": "core.serializers.auth.CustomTokenCreateSerializer",
    },
    "PERMISSIONS": {
        "user_create": ["djoser.permissions.CurrentUserOrAdmin"],
    },
}

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "simple_history.middleware.HistoryRequestMiddleware",
    "core.middlewares.logs.RequestLoggingMiddleware",
]

extra_delay_request = int(os.environ.get("EXTRA_DELAY_REQUEST", "0"))
if extra_delay_request:
    MIDDLEWARE.append("common.middlewares.delay.DelayMiddleware")

# CORS: never allow all origins by default. Development overrides this to True for
# convenience; production must set CORS_ALLOWED_ORIGINS (see production.py). Setting
# CORS_ALLOW_ALL_ORIGINS=true via env is supported but discouraged outside local dev.
CORS_ALLOW_ALL_ORIGINS = strtobool(os.environ.get("CORS_ALLOW_ALL_ORIGINS", "false"))
if os.environ.get("CORS_ALLOWED_ORIGINS"):
    CORS_ALLOWED_ORIGINS = os.environ.get("CORS_ALLOWED_ORIGINS").split(",")

ROOT_URLCONF = "aigle.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "aigle.wsgi.application"

# Database
DATABASES = {
    "default": {
        "ENGINE": os.environ.get("SQL_ENGINE", "django.db.backends.sqlite3"),
        "NAME": os.environ.get("SQL_DATABASE", BASE_DIR / "db.sqlite3"),
        "USER": os.environ.get("SQL_USER", "user"),
        "PASSWORD": os.environ.get("SQL_PASSWORD", "password"),
        "HOST": os.environ.get("SQL_HOST", "localhost"),
        "PORT": os.environ.get("SQL_PORT", "5432"),
    }
}

AUTH_USER_MODEL = "core.User"

# Password validation
PASSWORD_MIN_LENGTH = 8
AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {
            "min_length": PASSWORD_MIN_LENGTH,
        },
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ),
    # IsActiveAuthenticated (not bare IsAuthenticated) so DEACTIVATED accounts whose JWT
    # is still valid are locked out of every endpoint by default.
    "DEFAULT_PERMISSION_CLASSES": ["core.utils.permissions.IsActiveAuthenticated"],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.LimitOffsetPagination",
    "DEFAULT_THROTTLE_CLASSES": [
        "rest_framework.throttling.AnonRateThrottle",
        "rest_framework.throttling.UserRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        # Anonymous traffic (login, password reset, contact form, external test) is rare
        # and a prime brute-force target, so it is held tight. Authenticated users drive a
        # request-heavy map UI, so their ceiling is generous; "login" is a per-endpoint
        # scope applied to the token endpoints (see core/views/auth.py).
        "anon": os.environ.get("THROTTLE_ANON", "30/min"),
        "user": os.environ.get("THROTTLE_USER", "600/min"),
        "login": os.environ.get("THROTTLE_LOGIN", "5/min"),
    },
    "DEFAULT_RENDERER_CLASSES": (
        "djangorestframework_camel_case.render.CamelCaseJSONRenderer",
        "djangorestframework_camel_case.render.CamelCaseBrowsableAPIRenderer",
    ),
    "DEFAULT_PARSER_CLASSES": (
        "djangorestframework_camel_case.parser.CamelCaseFormParser",
        "djangorestframework_camel_case.parser.CamelCaseMultiPartParser",
        "djangorestframework_camel_case.parser.CamelCaseJSONParser",
    ),
    "DEFAULT_FILTER_BACKENDS": ["django_filters.rest_framework.DjangoFilterBackend"],
}

SIMPLE_JWT = {
    "AUTH_HEADER_TYPES": ("JWT",),
    # Short-lived access token: a leaked/stolen token is only usable for an hour, not a
    # month. The frontend transparently refreshes on 401, so this is invisible to users.
    # Refresh tokens last a week (was 180 days), bounding how long a stolen refresh token
    # grants access and forcing periodic re-authentication.
    "ACCESS_TOKEN_LIFETIME": timedelta(
        minutes=int(os.environ.get("ACCESS_TOKEN_LIFETIME_MINUTES", "60"))
    ),
    "REFRESH_TOKEN_LIFETIME": timedelta(
        days=int(os.environ.get("REFRESH_TOKEN_LIFETIME_DAYS", "7"))
    ),
    "UPDATE_LAST_LOGIN": True,
}

CORS_ALLOW_HEADERS = [
    "accept",
    "authorization",
    "content-type",
    "origin",
    "x-csrftoken",
    "x-requested-with",
    "x-user-group-uuid",
]

CORS_EXPOSE_HEADERS = [
    "content-disposition",
]

# Internationalization
LANGUAGE_CODE = "fr-FR"
TIME_ZONE = "UTC"
USE_I18N = True
USE_L10N = True
USE_TZ = True

LOCALE_PATHS = [
    BASE_DIR / "locale",
]

LANGUAGES = [
    ("fr", "Français"),
    ("en", "English"),
]

# Static files
STATIC_URL = "static/"

# Default primary key field type
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

MEDIA_ROOT = os.path.join(BASE_DIR, "media")

# Cache Configuration (Redis DB 1, separate from Celery on DB 0)
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": os.environ.get("CACHE_REDIS_URL", "redis://localhost:6379/1"),
    }
}

CELERY_BROKER_URL = "redis://localhost:6379/0"
CELERY_RESULT_BACKEND = "redis://localhost:6379/0"

# Redis re-delivers any task that runs longer than visibility_timeout (default 1h),
# silently re-executing long imports (→ duplicate detections). Must exceed the longest
# possible run, with wide margin since these imports are heavy and non-idempotent.
CELERY_BROKER_TRANSPORT_OPTIONS = {"visibility_timeout": 60 * 60 * 24}
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_TIMEZONE = "UTC"

CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_SEND_SENT_EVENT = True
CELERY_WORKER_SEND_TASK_EVENTS = True
CELERY_TASK_RESULT_EXPIRES = 3600

CELERY_TASK_ROUTES = {
    "core.utils.tasks.run_management_command": {"queue": "sequential_commands"},
}

CELERY_WORKER_CONCURRENCY = 1
CELERY_WORKER_PREFETCH_MULTIPLIER = 1

# A stuck task must not block the single sequential_commands worker forever, but big
# imports legitimately run up to ~12h. Soft limit raises inside the task so
# run_management_command's except/finally marks the row ERROR and the queue advances;
# hard limit SIGKILLs the child as a last resort. Must stay below visibility_timeout
# (24h) so a hung task is always killed before the broker would re-deliver it.
CELERY_TASK_SOFT_TIME_LIMIT = 60 * 60 * 15
CELERY_TASK_TIME_LIMIT = 60 * 60 * 16
