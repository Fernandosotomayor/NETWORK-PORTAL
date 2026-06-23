"""Legacy configuration file. Deprecated in favor of app.core.config."""

from __future__ import annotations

import warnings
from .core.config import settings

warnings.warn(
    "Importing from app.config is deprecated. Use app.core.config.settings instead.",
    DeprecationWarning,
    stacklevel=2,
)

BASE_DIR = settings.BASE_DIR
DATA_DIR = settings.DATA_DIR
TEMPLATES_DIR = settings.TEMPLATES_DIR
STATIC_DIR = settings.STATIC_DIR
