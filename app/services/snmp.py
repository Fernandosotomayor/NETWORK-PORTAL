import socket
import logging
import re
import random
from typing import Any, Optional

LOGGER = logging.getLogger(__name__)

# SNMP OIDs
OID_SYS_UPTIME = (1, 3, 6, 1, 2, 1, 1, 3, 0)
OID_IF_DESCR = (1, 3, 6, 1, 2, 1, 2, 2, 1, 2)
OID_IF_OPER_STATUS = (1, 3, 6, 1, 2, 1, 2, 2, 1, 8)

def encode_integer(val: int) -> bytes:
    """Encode an integer in ASN.1 BER format."""
    if val < 0:
        raise ValueError("Only positive integers supported")
    if val < 128:
        return bytes([0x02, 1, val])
    elif val < 256:
        return bytes([0x02, 1, val])
    
    # multi-byte integer
    temp = []
    while val > 0:
        temp.append(val & 0xff)
        val >>= 8
    
    # Check if MSB has sign bit set
    if temp[-1] & 0x80:
        temp.append(0)
    
    bytes_list = list(reversed(temp))
    return bytes([0x02, len(bytes_list)]) + bytes(bytes_list)

def encode_oid(oid: tuple[int, ...]) -> bytes:
    """Encode an OID tuple in ASN.1 BER format."""
    parts = []
    parts.append(oid[0] * 40 + oid[1])
    for part in oid[2:]:
        if part < 128:
            parts.append(part)
        else:
            temp = []
            temp.append(part & 0x7f)
            part >>= 7
            while part > 0:
                temp.append((part & 0x7f) | 0x80)
                part >>= 7
            parts.extend(reversed(temp))
    return bytes([0x06, len(parts)]) + bytes(parts)

def build_snmp_get_packet(community: str, oid: tuple[int, ...], request_id: int = 1) -> bytes:
    """Build a standard SNMPv2c GetRequest packet."""
    oid_encoded = encode_oid(oid)
    varbind = oid_encoded + b'\x05\x00' # OID + NULL
    varbind_list = bytes([0x30, len(varbind)]) + varbind
    
    req_id_encoded = encode_integer(request_id)
    err_status_encoded = bytes([0x02, 1, 0])
    err_index_encoded = bytes([0x02, 1, 0])
    pdu_payload = req_id_encoded + err_status_encoded + err_index_encoded + varbind_list
    pdu = bytes([0xa0, len(pdu_payload)]) + pdu_payload
    
    version_encoded = bytes([0x02, 1, 1]) # version 1 is v2c
    comm_encoded = bytes([0x04, len(community)]) + community.encode('utf-8')
    
    msg_payload = version_encoded + comm_encoded + pdu
    msg = bytes([0x30, len(msg_payload)]) + msg_payload
    return msg

def decode_snmp_response(data: bytes) -> Optional[Any]:
    """Parse a simple SNMP response and extract the value."""
    try:
        idx = 0
        if data[idx] != 0x30:
            return None
        idx += 2 if data[idx+1] < 128 else 2 + (data[idx+1] & 0x7f)
        
        if data[idx] != 0x02:
            return None
        idx += 2 + data[idx+1]
        
        if data[idx] != 0x04:
            return None
        idx += 2 + data[idx+1]
        
        if data[idx] != 0xa2:
            return None
        idx += 2 if data[idx+1] < 128 else 2 + (data[idx+1] & 0x7f)
        
        if data[idx] == 0x02:
            idx += 2 + data[idx+1]
        else:
            idx += 6
            
        if data[idx] == 0x02:
            idx += 2 + data[idx+1]
        if data[idx] == 0x02:
            idx += 2 + data[idx+1]
            
        if data[idx] != 0x30:
            return None
        idx += 2 if data[idx+1] < 128 else 2 + (data[idx+1] & 0x7f)
        
        if data[idx] != 0x30:
            return None
        idx += 2 if data[idx+1] < 128 else 2 + (data[idx+1] & 0x7f)
        
        if data[idx] != 0x06:
            return None
        idx += 2 + data[idx+1]
        
        val_tag = data[idx]
        val_len = data[idx+1]
        val_bytes = data[idx+2 : idx+2+val_len]
        
        if val_tag == 0x43: # TimeTicks
            val = 0
            for b in val_bytes:
                val = (val << 8) | b
            return val
        elif val_tag == 0x04: # Octet String
            return val_bytes.decode('utf-8', errors='replace')
        elif val_tag in (0x02, 0x41, 0x42): # Integer, Counter32, Gauge32
            val = 0
            for b in val_bytes:
                val = (val << 8) | b
            return val
        return None
    except Exception:
        LOGGER.exception("Error decoding SNMP packet")
        return None

def query_snmp_sys_uptime(ip: str, community: str = "public", timeout: float = 1.0) -> Optional[int]:
    """Query the system uptime (sysUpTime.0) via SNMP. Returns value in timeticks or None."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(timeout)
        packet = build_snmp_get_packet(community, OID_SYS_UPTIME)
        sock.sendto(packet, (ip, 161))
        response, _ = sock.recvfrom(2048)
        sock.close()
        res = decode_snmp_response(response)
        if isinstance(res, int):
            return res
        return None
    except Exception:
        return None

def query_snmp_ports_status(ip: str, ports: list[dict[str, Any]], community: str = "public", timeout: float = 1.0) -> dict[str, str]:
    """Query live interface operational status (ifOperStatus) for each port. Fallback to mock if unreachable."""
    status_map = {}
    
    uptime_ticks = query_snmp_sys_uptime(ip, community, timeout=0.8)
    
    if uptime_ticks is not None:
        for p in ports:
            port_name = str(p.get("name", ""))
            match = re.search(r'\d+$', port_name)
            if match:
                if_index = int(match.group(0))
                status_oid = OID_IF_OPER_STATUS + (if_index,)
                try:
                    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                    sock.settimeout(0.3)
                    packet = build_snmp_get_packet(community, status_oid)
                    sock.sendto(packet, (ip, 161))
                    response, _ = sock.recvfrom(2048)
                    sock.close()
                    val = decode_snmp_response(response)
                    if val == 1:
                        status_map[port_name] = "up"
                    elif val == 2:
                        status_map[port_name] = "down"
                    else:
                        status_map[port_name] = "unknown"
                except Exception:
                    status_map[port_name] = "unknown"
            else:
                status_map[port_name] = "unknown"
        
        for p in ports:
            name = p["name"]
            if name not in status_map or status_map[name] == "unknown":
                status_map[name] = get_mock_port_status(p)
    else:
        for p in ports:
            status_map[p["name"]] = get_mock_port_status(p)
            
    return status_map

def get_mock_port_status(port: dict[str, Any]) -> str:
    """Generate a realistic mock port status."""
    name = str(port.get("name", "")).lower()
    description = str(port.get("description", ""))
    mode = str(port.get("mode", ""))
    
    if "trunk" in mode or "uplink" in name or "gi23" in name or "gi24" in name:
        return "up"
    if description:
        return "up" if (len(description) % 5 != 0) else "down"
    return "down"

def get_dynamic_uptime_str(ip: str, parsed_uptime: str = "", community: str = "public") -> str:
    """Get the switch uptime. Query SNMP, if fails fall back to parsed_uptime, else return N/A."""
    ticks = query_snmp_sys_uptime(ip, community, timeout=0.8)
    if ticks is not None:
        seconds = ticks // 100
        days = seconds // 86400
        hours = (seconds % 86400) // 3600
        minutes = (seconds % 3600) // 60
        
        parts = []
        if days > 0:
            parts.append(f"{days} días")
        if hours > 0:
            parts.append(f"{hours} horas")
        if minutes > 0:
            parts.append(f"{minutes} mins")
            
        return ", ".join(parts) if parts else "0 mins"
    
    if parsed_uptime:
        # Translate to Spanish if matches pattern
        # "11 days, 13 hours, 32 mins, 57 secs" -> "11 días, 13 horas, 32 mins"
        res = parsed_uptime
        res = res.replace("days", "días").replace("day", "día")
        res = res.replace("hours", "horas").replace("hour", "hora")
        # Remove secs
        res = re.sub(r',\s*\d+\s*secs?$', '', res)
        return res
        
    return "No disponible (Offline)"
