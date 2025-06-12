"""
Django settings package for aigle project.

This package contains environment-specific settings modules.
The appropriate settings module is imported based on the ENVIRONMENT variable.
"""

import os

# Default to development if ENVIRONMENT is not set
ENVIRONMENT = os.environ.get("ENVIRONMENT", "development")

if ENVIRONMENT in ["production", "preprod"]:
    from .production import *  # noqa: F403, F401
else:
    from .development import *  # noqa: F403, F401
