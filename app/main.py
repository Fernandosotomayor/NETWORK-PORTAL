"""FastAPI web MVP for normalized Planet switch JSON files."""

from __future__ import annotations

import sys
import subprocess
import ipaddress
from typing import Any

import json
from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Request, UploadFile, File
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .core.config import settings
from .repository import JsonInventoryRepository, compact_vlan_list, port_matches_vlan
from .services.audit import generate_global_report
from .services.git_history import get_file_diff, get_file_history, get_recent_changes
from .services.topology import generate_topology, TopologyState, load_topology_state, save_topology_state
from .services.webhook import run_oxidized_sync
from .services.snmp import query_snmp_ports_status, get_dynamic_uptime_str

app = FastAPI(title="STLi Network Portal")
app.mount("/static", StaticFiles(directory=settings.STATIC_DIR), name="static")

templates = Jinja2Templates(directory=settings.TEMPLATES_DIR)
templates.env.filters["vlans"] = compact_vlan_list


def get_repository() -> JsonInventoryRepository:
    """Dependency to provide a JsonInventoryRepository instance."""
    return JsonInventoryRepository(settings.DATA_DIR)


@app.get("/", response_class=HTMLResponse)
def dashboard(
    request: Request,
    repository: JsonInventoryRepository = Depends(get_repository),
) -> HTMLResponse:
    switches = repository.list_switches()
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "active_page": "dashboard",
            "stats": repository.dashboard_stats(),
            "switches": switches,
            "warnings_count": sum(len(switch.warnings) for switch in switches),
        },
    )


@app.get("/inventory", response_class=HTMLResponse)
def inventory(
    request: Request,
    repository: JsonInventoryRepository = Depends(get_repository),
) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "inventory.html",
        {
            "active_page": "inventory",
            "switches": repository.list_switches(),
        },
    )


@app.get("/vlans", response_class=HTMLResponse)
def vlans_dashboard(
    request: Request,
    repository: JsonInventoryRepository = Depends(get_repository),
) -> HTMLResponse:
    """Aggregated VLAN inventory dashboard."""
    switches = repository.list_switches()
    vlans_map = {}
    
    for switch in switches:
        for vlan_id in switch.vlans:
            if vlan_id not in vlans_map:
                vlans_map[vlan_id] = {
                    "id": vlan_id,
                    "names": set(),
                    "ports": []
                }
            
            vlan_name = switch.vlan_names.get(str(vlan_id)) or switch.vlan_names.get(vlan_id)
            if vlan_name:
                vlans_map[vlan_id]["names"].add(vlan_name)
                
        for port in switch.ports:
            for vlan_id in list(vlans_map.keys()):
                if port_matches_vlan(port, vlan_id):
                    vlans_map[vlan_id]["ports"].append({
                        "switch_hostname": switch.hostname,
                        "switch_slug": switch.slug,
                        "port_name": port.get("name"),
                        "port_mode": port.get("mode"),
                        "description": port.get("description", "")
                    })

    vlans_list = []
    for vlan_id, data in vlans_map.items():
        names = sorted(list(data["names"]))
        vlan_name_str = ", ".join(names) if names else "VLAN " + str(vlan_id)
        vlans_list.append({
            "id": vlan_id,
            "name": vlan_name_str,
            "ports": data["ports"],
            "ports_count": len(data["ports"])
        })
        
    vlans_list.sort(key=lambda x: x["id"])
    
    total_vlans = len(vlans_list)
    most_used_vlan = None
    max_ports = -1
    for v in vlans_list:
        if v["ports_count"] > max_ports:
            max_ports = v["ports_count"]
            most_used_vlan = v
            
    all_changes = get_recent_changes(settings.BACKUPS_GIT_DIR)
    vlan_changes = [c for c in all_changes if "vlan" in c.message.lower()][:5]

    return templates.TemplateResponse(
        request,
        "vlans.html",
        {
            "active_page": "vlans",
            "vlans": vlans_list,
            "total_vlans": total_vlans,
            "most_used_vlan": most_used_vlan,
            "vlan_changes": vlan_changes,
        },
    )


@app.get("/switches/{slug}", response_class=HTMLResponse)
def switch_detail(
    request: Request,
    slug: str,
    repository: JsonInventoryRepository = Depends(get_repository),
) -> HTMLResponse:
    switch = repository.get_switch(slug)
    if switch is None:
        raise HTTPException(status_code=404, detail="Switch not found")

    history = get_file_history(settings.BACKUPS_GIT_DIR, switch.source_file)

    return templates.TemplateResponse(
        request,
        "switch_detail.html",
        {
            "active_page": "inventory",
            "switch": switch,
            "history": history,
        },
    )



@app.get("/search", response_class=HTMLResponse)
def search(
    request: Request,
    q: str = "",
    repository: JsonInventoryRepository = Depends(get_repository),
) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "search.html",
        {
            "active_page": "search",
            "query": q,
            "results": repository.search(q),
        },
    )


@app.get("/audit", response_class=HTMLResponse)
def audit(
    request: Request,
    repository: JsonInventoryRepository = Depends(get_repository),
) -> HTMLResponse:
    switches = repository.list_switches()
    report = generate_global_report(switches)
    return templates.TemplateResponse(
        request,
        "audit.html",
        {
            "active_page": "audit",
            "report": report,
        },
    )


@app.get("/changes", response_class=HTMLResponse)
def changes(
    request: Request,
    repository: JsonInventoryRepository = Depends(get_repository),
) -> HTMLResponse:
    changes = get_recent_changes(settings.BACKUPS_GIT_DIR)
    return templates.TemplateResponse(
        request,
        "changes.html",
        {
            "active_page": "changes",
            "changes": changes,
        },
    )


@app.get("/switches/diff/{commit_hash}", response_class=HTMLResponse)
def switch_diff(
    request: Request,
    commit_hash: str,
    filename: str,
    repository: JsonInventoryRepository = Depends(get_repository),
) -> HTMLResponse:
    diff_content = get_file_diff(settings.BACKUPS_GIT_DIR, filename, commit_hash)
    return templates.TemplateResponse(
        request,
        "diff_detail.html",
        {
            "active_page": "changes",
            "commit_hash": commit_hash,
            "filename": filename,
            "diff_content": diff_content,
        },
    )


@app.get("/topology", response_class=HTMLResponse)
def topology(
    request: Request,
    repository: JsonInventoryRepository = Depends(get_repository),
) -> HTMLResponse:
    switches = repository.list_switches()
    data = generate_topology(switches)
    return templates.TemplateResponse(
        request,
        "topology.html",
        {
            "active_page": "topology",
            "data": data.to_dict(),
        },
    )


@app.get("/api/topology/state", response_model=TopologyState)
def get_topology_state() -> TopologyState:
    """API endpoint to get current layout positions and topology config."""
    return load_topology_state(settings.STATE_FILE)


@app.post("/api/topology/state")
def post_topology_state(state: TopologyState) -> dict[str, str]:
    """API endpoint to save node layout positions and configs."""
    success = save_topology_state(settings.STATE_FILE, state)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to save state to file")
    return {"status": "success"}


@app.post("/api/webhooks/oxidized")
def post_webhook_oxidized(background_tasks: BackgroundTasks) -> dict[str, str]:
    """Webhook endpoint to receive Oxidized backup change events."""
    background_tasks.add_task(run_oxidized_sync)
    return {"status": "accepted", "message": "Synchronization started in the background"}


@app.post("/api/switches/{ip}/ping")
def post_ping_switch(
    ip: str,
    repository: JsonInventoryRepository = Depends(get_repository),
) -> dict[str, Any]:
    """Ping a switch IP address and return its online status, uptime, MAC and ping output."""
    try:
        ipaddress.IPv4Address(ip)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid IPv4 address")

    if sys.platform.startswith("win"):
        cmd = ["ping", "-n", "2", "-w", "2000", ip]
    else:
        cmd = ["ping", "-c", "2", "-W", "2", ip]

    # Find the switch record to get its parsed uptime/mac
    switch = None
    for s in repository.list_switches():
        if s.ip == ip:
            switch = s
            break

    parsed_uptime = switch.uptime if switch else ""
    mac = switch.mac if switch else ""

    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        is_online = res.returncode == 0
        uptime_str = get_dynamic_uptime_str(ip, parsed_uptime) if is_online else "Offline"
        
        return {
            "status": "success",
            "online": is_online,
            "output": res.stdout or res.stderr,
            "uptime": uptime_str,
            "mac": mac
        }
    except subprocess.TimeoutExpired:
        return {
            "status": "success",
            "online": False,
            "output": "Ping timeout expired",
            "uptime": "Offline",
            "mac": mac
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/switches/{ip}/ports/status")
def get_switch_ports_status(
    ip: str,
    repository: JsonInventoryRepository = Depends(get_repository),
) -> dict[str, Any]:
    """Retrieve operational status for all ports of a switch."""
    switch = None
    for s in repository.list_switches():
        if s.ip == ip:
            switch = s
            break
    if switch is None:
        raise HTTPException(status_code=404, detail="Switch not found")
        
    status_map = query_snmp_ports_status(ip, switch.ports)
    return {"status": "success", "ports": status_map}


@app.get("/api/switches/{ip}/download")
def download_switch_backup(
    ip: str,
    repository: JsonInventoryRepository = Depends(get_repository),
) -> FileResponse:
    """Download the latest backup configuration file for the switch."""
    switch = None
    for s in repository.list_switches():
        if s.ip == ip:
            switch = s
            break
            
    if switch is None or not switch.source_file:
        raise HTTPException(status_code=404, detail="Switch backup not found")
        
    cfg_filename = switch.source_file.replace('.json', '.cfg')
    file_path = settings.BACKUPS_GIT_DIR / cfg_filename
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Backup file not found on disk")
        
    return FileResponse(
        path=str(file_path),
        filename=cfg_filename,
        media_type="application/octet-stream"
    )


@app.post("/api/switches/{ip}/upload")
def upload_switch_backup(
    ip: str,
    file: UploadFile = File(...),
    repository: JsonInventoryRepository = Depends(get_repository),
) -> dict[str, Any]:
    """Upload a manual backup configuration for the switch."""
    import logging
    LOGGER = logging.getLogger(__name__)
    
    switch = None
    for s in repository.list_switches():
        if s.ip == ip:
            switch = s
            break
            
    if switch is None:
        raise HTTPException(status_code=404, detail="Switch not found")
        
    if not file.filename.endswith('.cfg') and not file.filename.endswith('.txt'):
        raise HTTPException(status_code=400, detail="Only .cfg or .txt files are allowed")
        
    try:
        contents = file.file.read()
        text_content = contents.decode('utf-8', errors='replace')
        
        # Generate new timestamped filename
        import datetime
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H%M%S")
        filename = f"{switch.hostname}_{timestamp}.cfg"
        cfg_path = settings.BACKUPS_GIT_DIR / filename
        
        # Save to backups directory
        settings.BACKUPS_GIT_DIR.mkdir(parents=True, exist_ok=True)
        cfg_path.write_bytes(contents)
        
        # Parse the configuration using the parser framework
        from parser.main import parse_file_with_metadata
        data = parse_file_with_metadata(cfg_path)
        
        # Save the normalized JSON file
        json_filename = f"{switch.hostname}_{timestamp}.json"
        json_path = settings.DATA_DIR / json_filename
        settings.DATA_DIR.mkdir(parents=True, exist_ok=True)
        json_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        
        # Commit the new configuration in Git
        try:
            subprocess.run(["git", "config", "--global", "--add", "safe.directory", "*"], capture_output=True, check=False)
            subprocess.run(["git", "add", filename], cwd=str(settings.BACKUPS_GIT_DIR), capture_output=True, text=True, check=True)
            status_res = subprocess.run(["git", "status", "--porcelain"], cwd=str(settings.BACKUPS_GIT_DIR), capture_output=True, text=True, check=True)
            if status_res.stdout.strip():
                subprocess.run(["git", "commit", "-m", f"Manual upload: {filename} by Administrator"], cwd=str(settings.BACKUPS_GIT_DIR), capture_output=True, text=True, check=True)
        except Exception as git_err:
            LOGGER.error(f"Git commit failed for manual upload: {git_err}")
            
        return {
            "status": "success",
            "message": "Configuration uploaded and normalized successfully",
            "filename": filename
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to process backup file: {str(e)}")


@app.get("/api/search/suggest")
def search_suggest(
    q: str = "",
    repository: JsonInventoryRepository = Depends(get_repository),
) -> dict[str, Any]:
    """Predictive autocomplete search suggestions endpoint."""
    normalized_query = q.strip().lower()
    results = {
        "switches": [],
        "ports": [],
        "vlans": []
    }
    
    if not normalized_query:
        return results
        
    switches = repository.list_switches()
    
    # 1. Search Switches (hostname, IP, model, location)
    for s in switches:
        if (normalized_query in s.hostname.lower() or 
            normalized_query in s.ip or 
            normalized_query in s.model.lower() or 
            normalized_query in s.location.lower()):
            results["switches"].append({
                "hostname": s.hostname,
                "ip": s.ip,
                "slug": s.slug,
                "model": s.model,
                "location": s.location
            })
            
    # 2. Search Ports (name, description)
    for s in switches:
        for port in s.ports:
            port_name = port.get("name", "")
            description = port.get("description", "")
            if (normalized_query in port_name.lower() or 
                normalized_query in description.lower()):
                results["ports"].append({
                    "switch_hostname": s.hostname,
                    "switch_slug": s.slug,
                    "port_name": port_name,
                    "description": description,
                    "mode": port.get("mode")
                })

    # 3. Search VLANs (ID or name)
    vlan_map = {}
    for s in switches:
        for vlan_id in s.vlans:
            vlan_name = s.vlan_names.get(str(vlan_id)) or s.vlan_names.get(vlan_id) or f"VLAN {vlan_id}"
            if vlan_id not in vlan_map:
                vlan_map[vlan_id] = {
                    "id": vlan_id,
                    "name": vlan_name,
                    "switches": set()
                }
            vlan_map[vlan_id]["switches"].add(s.hostname)
            if vlan_name != f"VLAN {vlan_id}":
                vlan_map[vlan_id]["name"] = vlan_name

    for vlan_id, data in vlan_map.items():
        id_str = str(vlan_id)
        name_str = data["name"].lower()
        if normalized_query in id_str or normalized_query in name_str:
            results["vlans"].append({
                "id": vlan_id,
                "name": data["name"],
                "switches_count": len(data["switches"])
            })

    results["switches"] = results["switches"][:5]
    results["ports"] = results["ports"][:5]
    results["vlans"] = results["vlans"][:5]
    
    return results




