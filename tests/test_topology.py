from __future__ import annotations

import unittest
from app.repository import SwitchRecord
from app.services.topology import generate_topology


class TopologyServiceTests(unittest.TestCase):
    def test_deduces_bidirectional_link_and_merges_ports(self) -> None:
        # SW-A connects to SW-B via gi1
        sw_a = SwitchRecord(
            slug="sw-a",
            source_file="sw-a.json",
            hostname="SW-A",
            ip="10.10.10.1",
            model="ModelA",
            firmware="v1.0",
            location="Rack1",
            vlans=[1],
            ports=[
                {
                    "name": "gi1",
                    "mode": "trunk",
                    "description": "Trunk_to_SW-B",
                }
            ],
            warnings=[],
        )

        # SW-B connects to SW-A via gi24
        sw_b = SwitchRecord(
            slug="sw-b",
            source_file="sw-b.json",
            hostname="SW-B",
            ip="10.10.10.2",
            model="ModelB",
            firmware="v1.0",
            location="Rack1",
            vlans=[1],
            ports=[
                {
                    "name": "gi24",
                    "mode": "trunk",
                    "description": "Trunk_to_SW-A",
                }
            ],
            warnings=[],
        )

        topology = generate_topology([sw_a, sw_b])

        self.assertEqual(len(topology.nodes), 2)
        # Should merge bidirectional links into exactly 1 link
        self.assertEqual(len(topology.links), 1)

        link = topology.links[0]
        # Nodes should be ordered alphabetically for standard output
        self.assertEqual(link.source, "sw-a")
        self.assertEqual(link.target, "sw-b")
        self.assertEqual(link.source_port, "gi1")
        self.assertEqual(link.target_port, "gi24")

    def test_deduces_unidirectional_link(self) -> None:
        # SW-A connects to SW-C via gi2, but SW-C does not mention SW-A
        sw_a = SwitchRecord(
            slug="sw-a",
            source_file="sw-a.json",
            hostname="SW-A",
            ip="10.10.10.1",
            model="ModelA",
            firmware="v1.0",
            location="Rack1",
            vlans=[1],
            ports=[
                {
                    "name": "gi2",
                    "mode": "trunk",
                    "description": "Trunk_to_SW-C",
                }
            ],
            warnings=[],
        )

        sw_c = SwitchRecord(
            slug="sw-c",
            source_file="sw-c.json",
            hostname="SW-C",
            ip="10.10.10.3",
            model="ModelC",
            firmware="v1.0",
            location="Rack2",
            vlans=[1],
            ports=[],
            warnings=[],
        )

        topology = generate_topology([sw_a, sw_c])

        self.assertEqual(len(topology.nodes), 2)
        self.assertEqual(len(topology.links), 1)

        link = topology.links[0]
        self.assertEqual(link.source, "sw-a")
        self.assertEqual(link.target, "sw-c")
        self.assertEqual(link.source_port, "gi2")
        self.assertIsNone(link.target_port)

    def test_prevents_self_loops(self) -> None:
        # SW-A description contains its own name, should not connect to itself
        sw_a = SwitchRecord(
            slug="sw-a",
            source_file="sw-a.json",
            hostname="SW-A",
            ip="10.10.10.1",
            model="ModelA",
            firmware="v1.0",
            location="Rack1",
            vlans=[1],
            ports=[
                {
                    "name": "gi1",
                    "mode": "trunk",
                    "description": "Trunk_to_self_SW-A",
                }
            ],
            warnings=[],
        )

        topology = generate_topology([sw_a])
        self.assertEqual(len(topology.links), 0)


import tempfile
from pathlib import Path
from app.services.topology import (
    TopologyState,
    Position,
    ManualLink,
    load_topology_state,
    save_topology_state,
)

class TopologyStateTests(unittest.TestCase):
    def test_state_save_and_load(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir) / "state.json"

            state = TopologyState(
                positions={
                    "sw-1": Position(x=100.5, y=-200.0)
                },
                background_url="floorplan.png",
                manual_links=[
                    ManualLink(source="sw-1", target="sw-2", source_port="gi1")
                ]
            )

            # Save
            save_success = save_topology_state(temp_path, state)
            self.assertTrue(save_success)
            self.assertTrue(temp_path.exists())

            # Load
            loaded_state = load_topology_state(temp_path)
            self.assertEqual(loaded_state.background_url, "floorplan.png")
            self.assertEqual(loaded_state.positions["sw-1"].x, 100.5)
            self.assertEqual(loaded_state.positions["sw-1"].y, -200.0)
            self.assertEqual(len(loaded_state.manual_links), 1)
            self.assertEqual(loaded_state.manual_links[0].source, "sw-1")

    def test_load_non_existent_returns_empty_state(self) -> None:
        non_existent_path = Path("/invalid/path/state.json")
        loaded_state = load_topology_state(non_existent_path)
        self.assertEqual(loaded_state.background_url, "")
        self.assertEqual(len(loaded_state.positions), 0)
