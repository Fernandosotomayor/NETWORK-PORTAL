"""Read-only repository for normalized parser JSON files."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class SwitchRecord:
    slug: str
    source_file: str
    hostname: str
    ip: str
    model: str
    firmware: str
    location: str
    mac: str = ""
    uptime: str = ""
    vlans: list[int] = field(default_factory=list)
    vlan_names: dict[str, str] = field(default_factory=dict)
    ports: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @classmethod
    def from_json(cls, path: Path, data: dict[str, Any]) -> "SwitchRecord":
        hostname = str(data.get("hostname") or path.stem)
        metadata = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}
        warnings = metadata.get("warnings") if isinstance(metadata, dict) else []
        return cls(
            slug=slugify(hostname),
            source_file=path.name,
            hostname=hostname,
            ip=str(data.get("ip") or ""),
            model=str(data.get("model") or ""),
            firmware=str(data.get("firmware") or ""),
            location=str(data.get("location") or ""),
            mac=str(data.get("mac") or ""),
            uptime=str(data.get("uptime") or ""),
            vlans=[int(vlan) for vlan in data.get("vlans", [])],
            vlan_names=dict(data.get("vlan_names") or {}),
            ports=list(data.get("ports", [])),
            warnings=list(warnings or []),
        )


@dataclass(slots=True)
class DashboardStats:
    switches: int
    unique_vlans: int
    ports: int


class JsonInventoryRepository:
    """Load normalized switch inventory exclusively from JSON files."""

    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir

    def list_switches(self) -> list[SwitchRecord]:
        # Group by switch base name to only load the latest version of each switch
        latest_paths: dict[str, tuple[str, Path]] = {}
        for json_path in self.data_dir.glob("*.json"):
            # Extract base name and timestamp
            # E.g., B-CENTRAL-BOD4_2026-06-23_223541.json -> base: B-CENTRAL-BOD4, ts: 2026-06-23_223541
            # E.g., B-CENTRAL-BOD4.json -> base: B-CENTRAL-BOD4, ts: ""
            match = re.search(r"^(.*?)(?:_(\d{4}-\d{2}-\d{2}_\d{6}))?$", json_path.stem)
            if match:
                base_name = match.group(1)
                timestamp = match.group(2) or ""
            else:
                base_name = json_path.stem
                timestamp = ""
            
            if base_name not in latest_paths:
                latest_paths[base_name] = (timestamp, json_path)
            else:
                existing_timestamp, _ = latest_paths[base_name]
                if timestamp > existing_timestamp:
                    latest_paths[base_name] = (timestamp, json_path)
                    
        records: list[SwitchRecord] = []
        for _, (_, json_path) in sorted(latest_paths.items()):
            try:
                data = json.loads(json_path.read_text(encoding="utf-8"))
                records.append(SwitchRecord.from_json(json_path, data))
            except (OSError, json.JSONDecodeError, TypeError, ValueError):
                LOGGER.exception("Unable to load normalized switch JSON: %s", json_path)
        return sorted(records, key=lambda item: item.hostname.lower())

    def get_switch(self, slug: str) -> SwitchRecord | None:
        for record in self.list_switches():
            if record.slug == slug:
                return record
        return None

    def dashboard_stats(self) -> DashboardStats:
        switches = self.list_switches()
        unique_vlans = {vlan for switch in switches for vlan in switch.vlans}
        port_count = sum(len(switch.ports) for switch in switches)
        return DashboardStats(
            switches=len(switches),
            unique_vlans=len(unique_vlans),
            ports=port_count,
        )

    def search(self, query: str) -> dict[str, list[dict[str, Any]]]:
        normalized_query = query.strip().lower()
        results: dict[str, list[dict[str, Any]]] = {"switches": [], "ports": [], "vlans": []}
        if not normalized_query:
            return results

        vlan_query = int(normalized_query) if normalized_query.isdigit() else None

        for switch in self.list_switches():
            if normalized_query in switch.hostname.lower():
                results["switches"].append({"switch": switch})

            if vlan_query is not None and vlan_query in switch.vlans:
                results["vlans"].append({"switch": switch, "vlan": vlan_query})

            for port in switch.ports:
                description = str(port.get("description") or "")
                if normalized_query in description.lower():
                    results["ports"].append({"switch": switch, "port": port, "reason": "description"})
                    continue

                if vlan_query is not None and port_matches_vlan(port, vlan_query):
                    results["ports"].append({"switch": switch, "port": port, "reason": "vlan"})

        return results


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "switch"


def port_matches_vlan(port: dict[str, Any], vlan_id: int) -> bool:
    vlan_fields = [port.get("access_vlan"), port.get("native_vlan")]
    if vlan_id in [vlan for vlan in vlan_fields if isinstance(vlan, int)]:
        return True
    for key in ("allowed_vlans", "hybrid_allowed_vlans"):
        values = port.get(key)
        if isinstance(values, list) and vlan_id in values:
            return True
    return False


def compact_vlan_list(vlans: list[int]) -> str:
    if not vlans:
        return "-"

    sorted_vlans = sorted(set(vlans))
    ranges: list[str] = []
    start = previous = sorted_vlans[0]

    for vlan_id in sorted_vlans[1:]:
        if vlan_id == previous + 1:
            previous = vlan_id
            continue
        ranges.append(str(start) if start == previous else f"{start}-{previous}")
        start = previous = vlan_id

    ranges.append(str(start) if start == previous else f"{start}-{previous}")
    return ", ".join(ranges)
