"""
Django settings for aigle project.

This file imports the appropriate settings module based on the ENVIRONMENT variable.
See the settings/ directory for environment-specific configurations.
"""

# Import all settings from the settings package
from .settings import *  # noqa: F403, F401
