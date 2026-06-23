"""Typed models for normalized switch backup data."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal


PortMode = Literal["access", "trunk", "hybrid", "unknown"]


@dataclass(slots=True)
class Vlan:
    """A configured VLAN."""

    id: int
    name: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class Port:
    """A normalized physical or logical switch port."""

    name: str
    mode: PortMode = "unknown"
    access_vlan: int | None = None
    native_vlan: int | None = None
    allowed_vlans: list[int] = field(default_factory=list)
    description: str = ""
    lldp: bool | None = None
    hybrid_allowed_vlans: list[int] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        if not self.hybrid_allowed_vlans:
            data.pop("hybrid_allowed_vlans")
        if not self.warnings:
            data.pop("warnings")
        return data


@dataclass(slots=True)
class BackupMetadata:
    """Metadata about the source backup file and parser run."""

    source_path: str
    parser_family: str
    line_count: int
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @classmethod
    def from_path(cls, path: Path, parser_family: str, line_count: int) -> "BackupMetadata":
        return cls(source_path=str(path), parser_family=parser_family, line_count=line_count)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class Switch:
    """Normalized switch configuration."""

    hostname: str = ""
    ip: str = ""
    model: str = ""
    firmware: str = ""
    location: str = ""
    vlans: list[Vlan] = field(default_factory=list)
    ports: list[Port] = field(default_factory=list)
    metadata: BackupMetadata | None = None
    management_vlan: int | None = None
    lldp_enabled: bool | None = None
    snmp: dict[str, Any] = field(default_factory=dict)

    def to_dict(self, include_metadata: bool = False) -> dict[str, Any]:
        data: dict[str, Any] = {
            "hostname": self.hostname,
            "ip": self.ip,
            "model": self.model,
            "firmware": self.firmware,
            "location": self.location,
            "vlans": [vlan.id for vlan in sorted(self.vlans, key=lambda item: item.id)],
            "ports": [port.to_dict() for port in self.ports],
        }
        if include_metadata:
            data["metadata"] = self.metadata.to_dict() if self.metadata else None
            data["management_vlan"] = self.management_vlan
            data["lldp_enabled"] = self.lldp_enabled
            data["snmp"] = self.snmp
        return data
