from __future__ import annotations

import unittest
from pathlib import Path

from parser.main import parse_file, parse_file_with_metadata
from parser.parser_factory import ParserFactory
from parser.planet_cisco_like_parser import PlanetCiscoLikeParser
from parser.planet_system_config_parser import PlanetSystemConfigParser


ROOT = Path(__file__).resolve().parents[1]
BACKUPS = ROOT / "backups"


class ParserFactoryTests(unittest.TestCase):
    def test_detects_system_config_family(self) -> None:
        text = (BACKUPS / "SW-CASCADA_2026-04-16_160404.cfg").read_text(encoding="utf-8")
        self.assertIsInstance(ParserFactory.from_text(text), PlanetSystemConfigParser)

    def test_detects_cisco_like_family(self) -> None:
        text = (BACKUPS / "PATIO-2-PRINCIPAL_2026-03-25_055507.cfg").read_text(encoding="utf-8")
        self.assertIsInstance(ParserFactory.from_text(text), PlanetCiscoLikeParser)


class ParseFileTests(unittest.TestCase):
    def test_system_config_metadata_and_ports(self) -> None:
        data = parse_file(BACKUPS / "SW-CASCADA_2026-04-16_160404.cfg")

        self.assertEqual(data["hostname"], "Sw3_Cascadas")
        self.assertEqual(data["ip"], "10.10.10.238")
        self.assertEqual(data["model"], "GS421024P2S")
        self.assertEqual(data["firmware"], "v3.0.5.48161.48161")
        self.assertEqual(data["location"], "DataCenter")
        self.assertIn(3999, data["vlans"])

        gi1 = next(port for port in data["ports"] if port["name"] == "gi1")
        self.assertEqual(gi1["mode"], "trunk")
        self.assertIn(150, gi1["allowed_vlans"])
        self.assertEqual(gi1["description"], "Trunk_to_Switch_Planificacion")

        gi11 = next(port for port in data["ports"] if port["name"] == "gi11")
        self.assertEqual(gi11["mode"], "access")
        self.assertEqual(gi11["access_vlan"], 12)

    def test_v4_system_config_uppercase_interfaces(self) -> None:
        data = parse_file(BACKUPS / "TORRE-CONTROL_2026-04-16_160404.cfg")

        self.assertEqual(data["hostname"], "TorreControl")
        self.assertEqual(data["model"], "GS-4210-24PL4C")
        self.assertEqual(data["firmware"], "v4.441b250728")

        ge1 = next(port for port in data["ports"] if port["name"] == "GE1")
        self.assertEqual(ge1["mode"], "trunk")
        self.assertEqual(ge1["native_vlan"], 45)
        self.assertEqual(ge1["allowed_vlans"], [2])

    def test_cisco_like_vlan_ranges_svi_and_hybrid(self) -> None:
        data = parse_file(BACKUPS / "PATIO-2-PRINCIPAL_2026-03-25_055507.cfg")

        self.assertEqual(data["hostname"], "IGS-5225-8P4S")
        self.assertEqual(data["ip"], "10.10.10.201")
        self.assertEqual(data["model"], "IGS-5225-8P4S")
        self.assertEqual(data["firmware"], "")
        self.assertEqual(data["vlans"], [1, 2, 3, 13, 14, 15, 50, 51, 52, 53, 100])

        trunk = next(port for port in data["ports"] if port["name"] == "GigabitEthernet 1/1")
        self.assertEqual(trunk["mode"], "trunk")
        self.assertEqual(trunk["native_vlan"], 100)

        hybrid = next(port for port in data["ports"] if port["name"] == "2.5GigabitEthernet 1/1")
        self.assertIn(45, hybrid["hybrid_allowed_vlans"])

    def test_all_backups_parse_to_required_shape(self) -> None:
        for cfg_path in BACKUPS.glob("*.cfg"):
            with self.subTest(path=cfg_path.name):
                data = parse_file(cfg_path)
                self.assertEqual(
                    sorted(data.keys()),
                    ["firmware", "hostname", "ip", "location", "model", "ports", "vlans"],
                )
                self.assertTrue(data["hostname"])
                self.assertTrue(data["ip"])
                self.assertIsInstance(data["vlans"], list)
                self.assertIsInstance(data["ports"], list)

    def test_metadata_reports_expected_warnings(self) -> None:
        data = parse_file_with_metadata(BACKUPS / "PATIO-2-PRINCIPAL_2026-03-25_055507.cfg")
        warnings = data["metadata"]["warnings"]
        self.assertIn("firmware not found", warnings)


if __name__ == "__main__":
    unittest.main()
