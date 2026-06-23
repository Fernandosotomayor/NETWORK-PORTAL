from __future__ import annotations

import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from app.main import app

class WebhookEndpointTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)

    @patch("app.main.run_oxidized_sync")
    def test_webhook_returns_accepted_and_triggers_sync_in_background(self, mock_sync) -> None:
        response = self.client.post("/api/webhooks/oxidized")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {
            "status": "accepted",
            "message": "Synchronization started in the background"
        })
        # Wait until background tasks execute in TestClient (which runs them synchronously by default)
        mock_sync.assert_called_once()
