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

    @patch("app.main.run_full_oxidized_sync_flow")
    def test_sync_endpoint_returns_accepted_and_triggers_sync_in_background(self, mock_sync_flow) -> None:
        response = self.client.post("/api/oxidized/sync")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {
            "status": "accepted",
            "message": "Full synchronization flow started in the background"
        })
        mock_sync_flow.assert_called_once()

    @patch("app.main.is_sync_in_progress", return_value=True)
    def test_sync_endpoint_returns_409_when_sync_already_in_progress(self, mock_in_progress) -> None:
        response = self.client.post("/api/oxidized/sync")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json(), {
            "detail": "Sincronización en curso. Por favor, espere a que termine."
        })

    @patch("app.main.is_sync_in_progress", return_value=True)
    @patch("app.main.get_last_commit_for_file")
    @patch("app.main.get_oxidized_nodes")
    def test_api_oxidized_status_returns_sync_in_progress(self, mock_nodes, mock_git, mock_in_progress) -> None:
        mock_nodes.return_value = [{"name": "SW1", "ip": "1.1.1.1", "status": "success"}]
        mock_git.return_value = {"hash": "abc", "date": "2026-06-26", "message": "commit"}
        response = self.client.get("/api/oxidized/status")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["sync_in_progress"])
