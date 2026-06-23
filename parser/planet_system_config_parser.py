"""Parser for Planet GS/WGS 4210 SYSTEM CONFIG FILE backups."""

from __future__ import annotations

import re

from .base_parser import BaseParser
from .models import Switch


class PlanetSystemConfigParser(BaseParser):
    """Parse Planet GS/WGS 4210 backups generated as SYSTEM CONFIG FILE."""

    family = "planet_system_config"

    def _parse_lines(self, lines: list[str]) -> Switch:
        switch = Switch(snmp={"enabled": None, "communities": [], "location": ""})
        vlan_ids: list[int] = []

        for line in lines:
            stripped = line.strip()

            if match := re.match(
                r"^! System Description:\s*PLANET\s+(.+?)\s+Switch$",
                stripped,
                flags=re.IGNORECASE,
            ):
                switch.model = match.group(1).strip()
                continue
            if match := re.match(r"^! System Version:\s*(.+)$", stripped, flags=re.IGNORECASE):
                switch.firmware = match.group(1).strip()
                continue
            if match := re.match(r"^! System Name:\s*(.+)$", stripped, flags=re.IGNORECASE):
                if not switch.hostname:
                    switch.hostname = match.group(1).strip()
                continue
            if match := re.match(r"^system name\s+(.+)$", stripped, flags=re.IGNORECASE):
                switch.hostname = self.clean_quoted(match.group(1))
                continue
            if match := re.match(r"^system location\s+(.+)$", stripped, flags=re.IGNORECASE):
                switch.location = self.clean_quoted(match.group(1))
                continue
            if match := re.match(
                r"^ip address\s+(\d+\.\d+\.\d+\.\d+)\s+mask\s+(\d+\.\d+\.\d+\.\d+)$",
                stripped,
                flags=re.IGNORECASE,
            ):
                switch.ip = match.group(1)
                continue
            if match := re.match(r"^vlan\s+([\d,\-]+)$", stripped, flags=re.IGNORECASE):
                vlan_ids.extend(self.expand_vlan_spec(match.group(1)))
                continue
            if match := re.match(r"^management-vlan vlan\s+(\d+)$", stripped, flags=re.IGNORECASE):
                switch.management_vlan = int(match.group(1))
                continue
            if re.fullmatch(r"lldp", stripped, flags=re.IGNORECASE):
                switch.lldp_enabled = True
                continue
            if re.match(r"^no snmp\b", stripped, flags=re.IGNORECASE):
                switch.snmp["enabled"] = False
                continue
            if re.match(r"^snmp\b", stripped, flags=re.IGNORECASE):
                switch.snmp["enabled"] = True
                if match := re.match(
                    r'^snmp community\s+"?([^"\s]+)"?\s+(ro|rw)',
                    stripped,
                    flags=re.IGNORECASE,
                ):
                    switch.snmp["communities"].append(
                        {"name": match.group(1), "access": match.group(2).lower()}
                    )

        switch.vlans = self.unique_vlans(vlan_ids)

        for name, block_lines in self.iter_interface_blocks(lines):
            if re.match(r"^vlan\b", name, flags=re.IGNORECASE):
                continue
            port = self.parse_port_block(name, block_lines)
            if self.is_configured_port(port):
                switch.ports.append(port)

        if switch.lldp_enabled is None:
            switch.lldp_enabled = False
        return switch
