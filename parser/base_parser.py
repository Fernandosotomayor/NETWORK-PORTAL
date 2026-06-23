"""Shared parser primitives for Planet switch backups."""

from __future__ import annotations

import logging
import re
from abc import ABC, abstractmethod
from pathlib import Path

from .models import BackupMetadata, Port, Switch, Vlan

LOGGER = logging.getLogger(__name__)


class BaseParser(ABC):
    """Base class for concrete Planet config parsers."""

    family = "base"

    def __init__(self) -> None:
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")

    def parse(self, text: str, source_path: Path) -> Switch:
        lines = text.splitlines()
        switch = self._parse_lines(lines)
        switch.metadata = BackupMetadata.from_path(source_path, self.family, len(lines))
        self._validate(switch)
        return switch

    @abstractmethod
    def _parse_lines(self, lines: list[str]) -> Switch:
        """Parse config lines into a normalized switch model."""

    @staticmethod
    def expand_vlan_spec(vlan_spec: str) -> list[int]:
        """Expand VLAN specs such as '1-3,10,100-101'."""
        vlans: set[int] = set()
        for raw_part in vlan_spec.split(","):
            part = raw_part.strip()
            if not part:
                continue
            if re.fullmatch(r"\d+-\d+", part):
                start_text, end_text = part.split("-", maxsplit=1)
                start = int(start_text)
                end = int(end_text)
                if start > end:
                    start, end = end, start
                vlans.update(range(start, end + 1))
            elif part.isdigit():
                vlans.add(int(part))
        return sorted(vlans)

    @staticmethod
    def unique_vlans(vlans: list[int]) -> list[Vlan]:
        return [Vlan(id=vlan_id) for vlan_id in sorted(set(vlans))]

    @staticmethod
    def compact_vlan_spec(vlans: list[int]) -> str:
        if not vlans:
            return ""

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
        return ",".join(ranges)

    @staticmethod
    def clean_quoted(value: str) -> str:
        value = value.strip()
        if len(value) >= 2 and value[0] == '"' and value[-1] == '"':
            return value[1:-1]
        return value

    @staticmethod
    def iter_interface_blocks(lines: list[str]) -> list[tuple[str, list[str]]]:
        blocks: list[tuple[str, list[str]]] = []
        current_name: str | None = None
        current_lines: list[str] = []

        for line in lines:
            match = re.match(r"^\s*interface\s+(.+?)\s*$", line, flags=re.IGNORECASE)
            if match:
                if current_name is not None:
                    blocks.append((current_name, current_lines))
                current_name = match.group(1).strip()
                current_lines = []
                continue
            if current_name is not None and (line.startswith(" ") or line.startswith("\t")):
                current_lines.append(line.strip())

        if current_name is not None:
            blocks.append((current_name, current_lines))

        return blocks

    def parse_port_block(self, name: str, block_lines: list[str]) -> Port:
        port = Port(name=name)
        mode_seen = False

        for line in block_lines:
            if match := re.match(r'^description\s+"?(.+?)"?$', line, flags=re.IGNORECASE):
                port.description = match.group(1)
                continue

            if match := re.match(r"^switchport mode\s+(\w+)", line, flags=re.IGNORECASE):
                mode = match.group(1).lower()
                if mode in {"access", "trunk", "hybrid"}:
                    port.mode = mode  # type: ignore[assignment]
                    mode_seen = True
                continue

            if match := re.match(r"^switchport access vlan\s+(\d+)", line, flags=re.IGNORECASE):
                port.access_vlan = int(match.group(1))
                if not mode_seen:
                    port.mode = "access"
                continue

            if match := re.match(r"^switchport trunk native vlan\s+(\d+)", line, flags=re.IGNORECASE):
                port.native_vlan = int(match.group(1))
                if not mode_seen:
                    port.mode = "trunk"
                continue

            if match := re.match(
                r"^switchport trunk allowed vlan(?:\s+add)?\s+([\d,\-]+)",
                line,
                flags=re.IGNORECASE,
            ):
                port.allowed_vlans = sorted(
                    set(port.allowed_vlans + self.expand_vlan_spec(match.group(1)))
                )
                if not mode_seen:
                    port.mode = "trunk"
                continue

            if match := re.match(
                r"^switchport hybrid allowed vlan\s+([\d,\-]+)",
                line,
                flags=re.IGNORECASE,
            ):
                port.hybrid_allowed_vlans = sorted(
                    set(port.hybrid_allowed_vlans + self.expand_vlan_spec(match.group(1)))
                )
                if not mode_seen and port.mode == "unknown":
                    port.mode = "hybrid"
                continue

            if re.match(r"^lldp\s+(?:receive|transmit|med|notification)", line, flags=re.IGNORECASE):
                port.lldp = True

        if port.mode == "access" and port.access_vlan is None:
            port.access_vlan = 1
            port.warnings.append("access port without explicit access VLAN; defaulted to VLAN 1")

        if port.mode == "unknown" and port.description:
            port.warnings.append("port has description but no explicit switchport mode")

        return port

    @staticmethod
    def is_configured_port(port: Port) -> bool:
        return any(
            [
                port.mode != "unknown",
                port.access_vlan is not None,
                port.native_vlan is not None,
                bool(port.allowed_vlans),
                bool(port.hybrid_allowed_vlans),
                bool(port.description),
            ]
        )

    def _validate(self, switch: Switch) -> None:
        if switch.metadata is None:
            return

        declared_vlans = {vlan.id for vlan in switch.vlans}
        if not switch.hostname:
            switch.metadata.errors.append("hostname not found")
        if not switch.ip:
            switch.metadata.errors.append("management IP not found")
        if not switch.model:
            switch.metadata.warnings.append("model not found")
        if not switch.firmware:
            switch.metadata.warnings.append("firmware not found")

        for port in switch.ports:
            referenced = set(port.allowed_vlans)
            if port.access_vlan is not None:
                referenced.add(port.access_vlan)
            if port.native_vlan is not None:
                referenced.add(port.native_vlan)
            referenced.update(port.hybrid_allowed_vlans)

            missing = sorted(vlan_id for vlan_id in referenced if declared_vlans and vlan_id not in declared_vlans)
            if missing:
                missing_spec = self.compact_vlan_spec(missing)
                port.warnings.append(f"references VLANs not declared globally: {missing_spec}")
                switch.metadata.warnings.append(f"{port.name} references undeclared VLANs {missing_spec}")

            for warning in port.warnings:
                self.logger.debug("%s: %s", port.name, warning)
