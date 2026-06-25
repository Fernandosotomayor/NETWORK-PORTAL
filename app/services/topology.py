"""Service to analyze network inventory and generate topology graph data."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
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
    firmware: str = ""
    location: str = ""
    uptime: str = ""
    vlans: list[int] = field(default_factory=list)
    port_count: int = 0
    trunk_count: int = 0
    link_count: int = 0
    warnings: list[str] = field(default_factory=list)


@dataclass(slots=True)
class NetworkLink:
    """A connection between two network nodes."""

    source: str
    target: str
    source_port: str | None
    target_port: str | None
    label: str
    link_type: str = "auto"  # "auto" | "manual"


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


# Regex patterns to extract switch target name from port descriptions
LINK_PATTERNS = [
    r"(?i)trunk[_\s]*(?:to|from)[_\s]*(?:sw|switch)[_\s]*(.+)",
    r"(?i)trunk[_\s]*sw[_\s]*(.+)",
    r"(?i)uplink[_\s]*(?:to|from)[_\s]*(?:sw|switch)?[_\s]*(.+)",
    r"(?i)(?:from|to)[_\s]*(?:sw|switch)[_\s]*(.+)",
    r"(?i)enlace[_\s]*(?:a|de|to|from)[_\s]*(?:sw|switch)?[_\s]*(.+)",
]

# Patterns that look like trunks but aren't switch-to-switch links
FALSE_POSITIVE_PATTERNS = [
    r"(?i)trunk[_\s]*\d+[UT]",           # "Trunk_10U_50T" (VLAN config hints)
    r"(?i)trunk[_\s]*vlan",              # "Trunk_VLAN1_only"
    r"(?i)trunk[_\s]*wifi",              # "Trunk_WiFi_AP"
    r"(?i)trunk[_\s]*generico",          # "Trunk_Generico"
    r"(?i)access[_\s]*vlan",             # "Access_VLAN10"
    r"(?i)disponible",                   # "Disponible_VLAN1"
]


def fuzzy_match_switch(extracted_name: str, switch_slugs: list[str]) -> str | None:
    """Match extracted target name against known switch slugs using fuzzy heuristics."""
    slug = slugify_desc(extracted_name)
    if not slug:
        return None
    
    # 1. Exact match
    if slug in switch_slugs:
        return slug
    
    # 2. Substring containment (either way)
    for known_slug in switch_slugs:
        if known_slug in slug or slug in known_slug:
            return known_slug
            
    # 3. Dash-insensitive matching
    slug_no_dash = slug.replace("-", "")
    for known_slug in switch_slugs:
        known_no_dash = known_slug.replace("-", "")
        if known_no_dash in slug_no_dash or slug_no_dash in known_no_dash:
            return known_slug
            
    return None


def is_connection_match(description: str, target_slug: str) -> bool:
    """Check if a port description matches a target switch slug using word boundaries."""
    desc_clean = slugify_desc(description)
    if not desc_clean:
        return False

    padded_desc = f"-{desc_clean}-"
    padded_target = f"-{target_slug}-"
    if padded_target in padded_desc:
        return True

    # Check without dashes for variations
    target_no_dash = target_slug.replace("-", "")
    padded_target_no_dash = f"-{target_no_dash}-"
    if padded_target_no_dash in padded_desc:
        return True

    return False


def generate_topology(switches: list[SwitchRecord]) -> TopologyData:
    """Deduce network nodes and interconnecting links from switch records."""
    # 1. Build slugs list
    switch_slugs = [s.slug for s in switches]
    switch_map = {s.slug: s for s in switches}

    # 2. Compile patterns
    compiled_patterns = [re.compile(p) for p in LINK_PATTERNS]
    compiled_false_positives = [re.compile(p) for p in FALSE_POSITIVE_PATTERNS]

    # Intermediate link storage: key=(min_slug, max_slug) -> dict
    links_map: dict[tuple[str, str], dict[str, Any]] = {}

    for switch in switches:
        for port in switch.ports:
            desc = str(port.get("description") or "").strip()
            if not desc:
                continue

            # Skip false positives
            if any(pat.search(desc) for pat in compiled_false_positives):
                continue

            # Try regex matching
            target_slug = None
            for pat in compiled_patterns:
                match = pat.search(desc)
                if match:
                    extracted = match.group(1).strip().rstrip("_")
                    target_slug = fuzzy_match_switch(extracted, switch_slugs)
                    if target_slug:
                        break

            # Fallback to original substring matching if regex didn't resolve
            if not target_slug:
                for other_slug in switch_slugs:
                    if other_slug != switch.slug and is_connection_match(desc, other_slug):
                        target_slug = other_slug
                        break

            if target_slug and target_slug != switch.slug:
                min_slug = min(switch.slug, target_slug)
                max_slug = max(switch.slug, target_slug)
                key = (min_slug, max_slug)

                if key not in links_map:
                    links_map[key] = {
                        "source": min_slug,
                        "target": max_slug,
                        "source_port": None,
                        "target_port": None,
                        "link_type": "auto"
                    }

                # Associate ports correctly
                port_name = port.get("name")
                if switch.slug == min_slug:
                    links_map[key]["source_port"] = port_name
                else:
                    links_map[key]["target_port"] = port_name

    # Build final link list
    links: list[NetworkLink] = []
    for key, data in links_map.items():
        s_port = data["source_port"]
        t_port = data["target_port"]

        # Format label
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
                link_type=data["link_type"]
            )
        )

    # Build nodes list with full metadata
    nodes: list[NetworkNode] = []
    link_counts = {slug: 0 for slug in switch_slugs}

    for link in links:
        if link.source in link_counts:
            link_counts[link.source] += 1
        if link.target in link_counts:
            link_counts[link.target] += 1

    for switch in switches:
        port_count = len(switch.ports)
        trunk_count = sum(
            1 for p in switch.ports
            if any(term in str(p.get("description") or "").lower() for term in ["trunk", "uplink", "enlace"])
        )
        nodes.append(
            NetworkNode(
                id=switch.slug,
                label=switch.hostname,
                ip=switch.ip,
                model=switch.model,
                group="switch",
                firmware=switch.firmware,
                location=switch.location,
                uptime=switch.uptime,
                vlans=switch.vlans,
                port_count=port_count,
                trunk_count=trunk_count,
                link_count=link_counts.get(switch.slug, 0),
                warnings=switch.warnings
            )
        )

    return TopologyData(nodes=nodes, links=links)
