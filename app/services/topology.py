"""Service to analyze network inventory and generate topology graph data."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional
from pydantic import BaseModel
from app.repository import SwitchRecord


class Position(BaseModel):
    """X and Y coordinates for a node."""

    x: float
    y: float


class ManualLink(BaseModel):
    """A manual user-defined link between two switches."""

    source: str
    target: str
    source_port: Optional[str] = None
    target_port: Optional[str] = None


class TopologyState(BaseModel):
    """The saved layout and configuration state of the topology map."""

    positions: Dict[str, Position] = {}
    background_url: str = ""
    manual_links: List[ManualLink] = []


def load_topology_state(state_file_path: Path) -> TopologyState:
    """Load topology state from JSON file with defensive error handling."""
    if not state_file_path.exists():
        return TopologyState()
    try:
        content = state_file_path.read_text(encoding="utf-8").strip()
        if not content:
            return TopologyState()
        data = json.loads(content)
        return TopologyState(**data)
    except (json.JSONDecodeError, OSError, ValueError):
        return TopologyState()


def save_topology_state(state_file_path: Path, state: TopologyState) -> bool:
    """Save topology state to JSON file with defensive error handling."""
    try:
        state_file_path.parent.mkdir(parents=True, exist_ok=True)
        state_file_path.write_text(
            state.model_dump_json(indent=2),
            encoding="utf-8",
        )
        return True
    except OSError:
        return False


@dataclass(slots=True)
class NetworkNode:
    """A node in the network topology graph."""

    id: str
    label: str
    ip: str
    model: str
    group: str = "switch"


@dataclass(slots=True)
class NetworkLink:
    """A connection between two network nodes."""

    source: str
    target: str
    source_port: str | None
    target_port: str | None
    label: str


@dataclass(slots=True)
class TopologyData:
    """Consolidated topology graph dataset."""

    nodes: list[NetworkNode]
    links: list[NetworkLink]

    def to_dict(self) -> dict[str, Any]:
        """Convert the topology dataset into a JSON-serializable dictionary."""
        import dataclasses
        return dataclasses.asdict(self)


def slugify_desc(value: str) -> str:
    """Helper to clean and slugify a description string."""
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def is_connection_match(description: str, target_slug: str) -> bool:
    """Check if a port description matches a target switch slug using word boundaries."""
    desc_clean = slugify_desc(description)
    if not desc_clean:
        return False

    padded_desc = f"-{desc_clean}-"
    padded_target = f"-{target_slug}-"
    if padded_target in padded_desc:
        return True

    # Check without dashes for variations (e.g. porteriacentral matching porteria-central)
    target_no_dash = target_slug.replace("-", "")
    padded_target_no_dash = f"-{target_no_dash}-"
    if padded_target_no_dash in padded_desc:
        return True

    return False


def generate_topology(switches: list[SwitchRecord]) -> TopologyData:
    """Deduce network nodes and interconnecting links from switch records."""
    nodes: list[NetworkNode] = []
    # Map from slug to switch record for quick lookups
    switch_map = {s.slug: s for s in switches}

    for switch in switches:
        nodes.append(
            NetworkNode(
                id=switch.slug,
                label=switch.hostname,
                ip=switch.ip,
                model=switch.model,
                group="switch",
            )
        )

    # Intermediate link storage: key=(min_slug, max_slug) -> dict
    links_map: dict[tuple[str, str], dict[str, Any]] = {}

    for switch in switches:
        for port in switch.ports:
            desc = str(port.get("description") or "").strip()
            if not desc:
                continue

            # Look for matches with other switches
            for other_switch in switches:
                if other_switch.slug == switch.slug:
                    continue

                if is_connection_match(desc, other_switch.slug):
                    # Found a connection
                    min_slug = min(switch.slug, other_switch.slug)
                    max_slug = max(switch.slug, other_switch.slug)
                    key = (min_slug, max_slug)

                    if key not in links_map:
                        links_map[key] = {
                            "source": min_slug,
                            "target": max_slug,
                            "source_port": None,
                            "target_port": None,
                        }

                    # Determine if this port belongs to the source (min_slug) or target (max_slug)
                    if switch.slug == min_slug:
                        links_map[key]["source_port"] = port.get("name")
                    else:
                        links_map[key]["target_port"] = port.get("name")

    # Build final link list
    links: list[NetworkLink] = []
    for key, data in links_map.items():
        s_port = data["source_port"]
        t_port = data["target_port"]

        # Format label (e.g. "gi1 <-> gi2" or "gi1 -> ?")
        if s_port and t_port:
            label = f"{s_port} <-> {t_port}"
        elif s_port:
            label = f"{s_port} -> ?"
        else:
            label = f"? <- {t_port}"

        links.append(
            NetworkLink(
                source=data["source"],
                target=data["target"],
                source_port=s_port,
                target_port=t_port,
                label=label,
            )
        )

    return TopologyData(nodes=nodes, links=links)
