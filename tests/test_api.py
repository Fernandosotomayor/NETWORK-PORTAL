from __future__ import annotations

import unittest
from pathlib import Path
from fastapi.testclient import TestClient

from app.main import app
from app.core.config import settings

class ApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)

    def test_search_suggest_empty(self) -> None:
        response = self.client.get("/api/search/suggest?q=")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data, {"switches": [], "ports": [], "vlans": []})

    def test_search_suggest_with_query(self) -> None:
        response = self.client.get("/api/search/suggest?q=central")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("switches", data)
        self.assertIn("ports", data)
        self.assertIn("vlans", data)

    def test_ports_status(self) -> None:
        # gs4210 IP: 10.10.10.203 (B-CENTRAL-BOD4)
        response = self.client.get("/api/switches/10.10.10.203/ports/status")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "success")
        self.assertIn("ports", data)

    def test_download_backup(self) -> None:
        response = self.client.get("/api/switches/10.10.10.203/download")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "application/octet-stream")

    def test_vlans_dashboard_html(self) -> None:
        response = self.client.get("/vlans")
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/html", response.headers["content-type"])
        self.assertIn(b"Dashboard de VLANs", response.content)

    def test_refresh_vlans_cache(self) -> None:
        response = self.client.post("/api/vlans/refresh")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "success")
        self.assertIn("last_updated", data)
