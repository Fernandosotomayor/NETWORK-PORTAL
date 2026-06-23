from __future__ import annotations

import unittest
from app.repository import SwitchRecord
from app.services.audit import audit_switch


class AuditServiceTests(unittest.TestCase):
    def test_detects_orphan_vlan(self) -> None:
        # Switch has global vlans [1, 10]
        # Port gi1 has access_vlan=20 (orphan)
        switch = SwitchRecord(
            slug="test-switch",
            source_file="test.json",
            hostname="TestSwitch",
            ip="10.10.10.1",
            model="ModelX",
            firmware="v1.0",
            location="Rack1",
            vlans=[1, 10],
            ports=[
                {
                    "name": "gi1",
                    "mode": "access",
                    "access_vlan": 20,
                    "description": "Orphan Access Port",
                }
            ],
            warnings=[],
        )
        findings = audit_switch(switch)
        orphan_findings = [f for f in findings if f.rule_id == "orphan_vlan"]
        self.assertEqual(len(orphan_findings), 1)
        self.assertEqual(orphan_findings[0].severity, "critical")
        self.assertEqual(orphan_findings[0].port_name, "gi1")
        self.assertIn("VLAN 20", orphan_findings[0].message)

    def test_detects_suspect_trunk(self) -> None:
        # Trunk port with empty allowed_vlans
        switch = SwitchRecord(
            slug="test-switch",
            source_file="test.json",
            hostname="TestSwitch",
            ip="10.10.10.1",
            model="ModelX",
            firmware="v1.0",
            location="Rack1",
            vlans=[1, 10],
            ports=[
                {
                    "name": "gi2",
                    "mode": "trunk",
                    "native_vlan": 1,
                    "allowed_vlans": [],
                    "description": "Suspect Trunk",
                }
            ],
            warnings=[],
        )
        findings = audit_switch(switch)
        trunk_findings = [f for f in findings if f.rule_id == "empty_trunk"]
        self.assertEqual(len(trunk_findings), 1)
        self.assertEqual(trunk_findings[0].severity, "critical")
        self.assertEqual(trunk_findings[0].port_name, "gi2")

    def test_detects_missing_description(self) -> None:
        # Configured port without description
        switch = SwitchRecord(
            slug="test-switch",
            source_file="test.json",
            hostname="TestSwitch",
            ip="10.10.10.1",
            model="ModelX",
            firmware="v1.0",
            location="Rack1",
            vlans=[1, 10],
            ports=[
                {
                    "name": "gi3",
                    "mode": "access",
                    "access_vlan": 10,
                    "description": "",  # Empty description
                }
            ],
            warnings=[],
        )
        findings = audit_switch(switch)
        desc_findings = [f for f in findings if f.rule_id == "missing_description"]
        self.assertEqual(len(desc_findings), 1)
        self.assertEqual(desc_findings[0].severity, "warning")
        self.assertEqual(desc_findings[0].port_name, "gi3")

    def test_ignores_non_configured_ports_for_description(self) -> None:
        # Unconfigured port should not trigger missing description warning
        switch = SwitchRecord(
            slug="test-switch",
            source_file="test.json",
            hostname="TestSwitch",
            ip="10.10.10.1",
            model="ModelX",
            firmware="v1.0",
            location="Rack1",
            vlans=[1, 10],
            ports=[
                {
                    "name": "gi4",
                    "mode": "unknown",
                    "description": "",
                }
            ],
            warnings=[],
        )
        findings = audit_switch(switch)
        desc_findings = [f for f in findings if f.rule_id == "missing_description"]
        self.assertEqual(len(desc_findings), 0)
