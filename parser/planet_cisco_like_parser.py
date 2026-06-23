"""Parser for Planet IGS Cisco-like running-config backups."""

from __future__ import annotations

import re

from .base_parser import BaseParser
from .models import Switch


class PlanetCiscoLikeParser(BaseParser):
    """Parse Planet IGS running-config style backups."""

    family = "planet_cisco_like"

    def _parse_lines(self, lines: list[str]) -> Switch:
        switch = Switch(snmp={"enabled": None, "communities": [], "location": ""})
        vlan_ids: list[int] = []

        for line in lines:
            stripped = line.strip()

            if match := re.match(r"^(.+?)#\s+show running-config$", stripped, flags=re.IGNORECASE):
                prompt_name = match.group(1).strip()
                if not switch.model and re.search(r"\d", prompt_name):
                    switch.model = prompt_name
                continue
            if match := re.match(r"^hostname\s+(.+)$", stripped, flags=re.IGNORECASE):
                switch.hostname = match.group(1).strip()
                if not switch.model and re.search(r"\d", switch.hostname):
                    switch.model = switch.hostname
                continue
            if match := re.match(r"^vlan\s+([\d,\-]+)$", stripped, flags=re.IGNORECASE):
                vlan_ids.extend(self.expand_vlan_spec(match.group(1)))
                continue
            if re.match(r"^no snmp-server\b", stripped, flags=re.IGNORECASE):
                switch.snmp["enabled"] = False
                continue
            if re.match(r"^snmp-server\b", stripped, flags=re.IGNORECASE):
                switch.snmp["enabled"] = True
                if match := re.match(r"^snmp-server location\s+(.+)$", stripped, flags=re.IGNORECASE):
                    switch.location = match.group(1).strip()
                    switch.snmp["location"] = switch.location
                continue
            if re.fullmatch(r"lldp", stripped, flags=re.IGNORECASE):
                switch.lldp_enabled = True

        switch.vlans = self.unique_vlans(vlan_ids)

        for name, block_lines in self.iter_interface_blocks(lines):
            if re.match(r"^vlan\b", name, flags=re.IGNORECASE):
                for block_line in block_lines:
                    if match := re.match(
                        r"^ip address\s+(\d+\.\d+\.\d+\.\d+)\s+(\d+\.\d+\.\d+\.\d+)$",
                        block_line,
                        flags=re.IGNORECASE,
                    ):
                        switch.ip = match.group(1)
                        if vlan_match := re.match(r"^vlan\s+(\d+)$", name, flags=re.IGNORECASE):
                            switch.management_vlan = int(vlan_match.group(1))
                continue

            port = self.parse_port_block(name, block_lines)
            if self.is_configured_port(port):
                switch.ports.append(port)

        if switch.lldp_enabled is None:
            switch.lldp_enabled = False
        return switch
