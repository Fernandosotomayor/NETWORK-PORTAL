"""Audit service to detect logical configuration inconsistencies in switch records."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal
from app.repository import SwitchRecord, compact_vlan_list


@dataclass(slots=True)
class AuditFinding:
    """A single configuration inconsistency finding."""

    switch_hostname: str
    switch_slug: str
    port_name: str | None
    severity: Literal["critical", "warning"]
    rule_id: Literal["orphan_vlan", "empty_trunk", "missing_description"]
    message: str


@dataclass(slots=True)
class AuditReport:
    """A complete audit report across all switches."""

    findings: list[AuditFinding]
    critical_count: int
    warning_count: int


def is_configured_port(port: dict[str, Any]) -> bool:
    """Check if a port has any active configuration."""
    return any(
        [
            port.get("mode") != "unknown",
            port.get("access_vlan") is not None,
            port.get("native_vlan") is not None,
            bool(port.get("allowed_vlans")),
            bool(port.get("hybrid_allowed_vlans")),
            port.get("lldp") is not None,
        ]
    )


def audit_switch(switch: SwitchRecord) -> list[AuditFinding]:
    """Audit a single switch record and return all findings."""
    findings: list[AuditFinding] = []
    global_vlans = set(switch.vlans)

    for port in switch.ports:
        port_name = str(port.get("name") or "")

        # --- Rule 1: Orphan VLANs (Critical) ---
        referenced_vlans: set[int] = set()
        if port.get("access_vlan") is not None:
            referenced_vlans.add(int(port["access_vlan"]))
        if port.get("native_vlan") is not None:
            referenced_vlans.add(int(port["native_vlan"]))
        for vlan in port.get("allowed_vlans") or []:
            referenced_vlans.add(int(vlan))
        for vlan in port.get("hybrid_allowed_vlans") or []:
            referenced_vlans.add(int(vlan))

        # Check against global vlans (only if global vlans is defined)
        if global_vlans:
            orphans = sorted(v for v in referenced_vlans if v not in global_vlans)
            if orphans:
                vlan_str = compact_vlan_list(orphans)
                findings.append(
                    AuditFinding(
                        switch_hostname=switch.hostname,
                        switch_slug=switch.slug,
                        port_name=port_name,
                        severity="critical",
                        rule_id="orphan_vlan",
                        message=f"VLAN {vlan_str} not declared globally.",
                    )
                )

        # --- Rule 2: Empty Trunk (Critical) ---
        if port.get("mode") == "trunk":
            allowed = port.get("allowed_vlans") or []
            if not allowed:
                findings.append(
                    AuditFinding(
                        switch_hostname=switch.hostname,
                        switch_slug=switch.slug,
                        port_name=port_name,
                        severity="critical",
                        rule_id="empty_trunk",
                        message="Trunk port is configured but allows no VLANs.",
                    )
                )

        # --- Rule 3: Missing Description (Warning) ---
        if is_configured_port(port):
            desc = str(port.get("description") or "").strip()
            if not desc:
                findings.append(
                    AuditFinding(
                        switch_hostname=switch.hostname,
                        switch_slug=switch.slug,
                        port_name=port_name,
                        severity="warning",
                        rule_id="missing_description",
                        message="Configured port is missing a description.",
                    )
                )

    return findings


def generate_global_report(switches: list[SwitchRecord]) -> AuditReport:
    """Generate a consolidated audit report across all switches."""
    all_findings: list[AuditFinding] = []
    critical_count = 0
    warning_count = 0

    for switch in switches:
        findings = audit_switch(switch)
        all_findings.extend(findings)
        for finding in findings:
            if finding.severity == "critical":
                critical_count += 1
            else:
                warning_count += 1

    return AuditReport(
        findings=all_findings,
        critical_count=critical_count,
        warning_count=warning_count,
    )
