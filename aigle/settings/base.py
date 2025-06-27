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
    "core",
    "djoser",
    "django_filters",
    "debug_toolbar",
    "simple_history",
]

# Email configuration
EMAIL_BACKEND = os.environ.get("EMAIL_BACKEND")
EMAIL_HOST = os.environ.get("EMAIL_HOST")
EMAIL_PORT = os.environ.get("EMAIL_PORT")
EMAIL_USE_TLS = os.environ.get("EMAIL_USE_TLS")
EMAIL_HOST_USER = os.environ.get("EMAIL_HOST_USER")
EMAIL_HOST_PASSWORD = os.environ.get("EMAIL_HOST_PASSWORD")
DEFAULT_FROM_EMAIL = os.environ.get("DEFAULT_FROM_EMAIL")

# Djoser configuration
DJOSER = {
    "PASSWORD_RESET_CONFIRM_URL": "reset-password/{uid}/{token}",
    "LOGIN_FIELD": "email",
    "SERIALIZERS": {
        "current_user": "core.serializers.user.UserSerializer",
    },
    "PERMISSIONS": {
        "user_create": ["djoser.permissions.CurrentUserOrAdmin"],
    },
}

MIDDLEWARE = [
    "debug_toolbar.middleware.DebugToolbarMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "simple_history.middleware.HistoryRequestMiddleware",
    "core.middlewares.logs.RequestLoggingMiddleware",
]

# Extra middlewares
extra_delay_request = int(os.environ.get("EXTRA_DELAY_REQUEST", "0"))
if extra_delay_request:
    MIDDLEWARE.append("common.middlewares.delay.DelayMiddleware")

CORS_ALLOW_ALL_ORIGINS = True

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

# REST framework
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ),
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.LimitOffsetPagination",
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
    "ACCESS_TOKEN_LIFETIME": timedelta(days=30),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=180),
    "UPDATE_LAST_LOGIN": True,
}

CORS_EXPOSE_HEADERS = [
    "content-disposition",
]

# Internationalization
LANGUAGE_CODE = "fr"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

# Static files
STATIC_URL = "static/"

# Default primary key field type
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

MEDIA_ROOT = os.path.join(BASE_DIR, "media")

# Celery Configuration
CELERY_BROKER_URL = "redis://localhost:6379/0"
CELERY_RESULT_BACKEND = "redis://localhost:6379/0"
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_TIMEZONE = "UTC"

# Task execution and monitoring settings
CELERY_TASK_TRACK_STARTED = True  # Track when task starts executing
CELERY_TASK_SEND_SENT_EVENT = True  # Send task-sent events
CELERY_WORKER_SEND_TASK_EVENTS = True  # Enable task events for monitoring
CELERY_TASK_RESULT_EXPIRES = 3600  # Keep task results for 1 hour

# Task routing for sequential execution
CELERY_ROUTES = {
    "core.utils.tasks.run_management_command": {"queue": "sequential_commands"},
    "core.utils.tasks.run_custom_command": {"queue": "sequential_commands"},
}

# Worker configuration for sequential processing
CELERY_WORKER_CONCURRENCY = 1  # Only one task at a time
CELERY_WORKER_PREFETCH_MULTIPLIER = 1  # Don't prefetch tasks
