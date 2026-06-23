from __future__ import annotations

import unittest
from app.core.config import Settings


class ConfigTests(unittest.TestCase):
    def test_settings_load_defaults(self) -> None:
        settings = Settings()
        self.assertEqual(settings.APP_ENV, "development")
        self.assertTrue(settings.DATA_DIR.is_absolute())
        self.assertTrue(settings.STATIC_DIR.is_absolute())
        self.assertTrue(settings.TEMPLATES_DIR.is_absolute())
