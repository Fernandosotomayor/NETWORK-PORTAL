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
from .services.git_history import get_file_diff, get_file_history, get_recent_changes, get_last_global_backup_time, get_last_commit_for_file
from .services.topology import generate_topology, TopologyState, load_topology_state, save_topology_state
from .services.webhook import run_oxidized_sync
from .services.snmp import query_snmp_ports_status, get_dynamic_uptime_str
from .services.oxidized import get_oxidized_nodes

app = FastAPI(title="STLi Network Portal")
app.mount("/static", StaticFiles(directory=settings.STATIC_DIR), name="static")

templates = Jinja2Templates(directory=settings.TEMPLATES_DIR)
templates.env.filters["vlans"] = compact_vlan_list
templates.env.globals["get_last_backup_time"] = lambda: get_last_global_backup_time(settings.BACKUPS_GIT_DIR)



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


def aggregate_vlans_data(repository: JsonInventoryRepository) -> dict[str, Any]:
    """Perform O(S*P) aggregation of VLANs from switch records."""
    switches = repository.list_switches()
    vlans_map = {}
    
    # 1. Initialize all VLANs defined on the switches
    for switch in switches:
        for vlan_id in switch.vlans:
            if vlan_id not in vlans_map:
                vlans_map[vlan_id] = {
                    "id": vlan_id,
                    "names": set(),
                    "switches": {}
                }
            
            vlan_name = switch.vlan_names.get(str(vlan_id)) or switch.vlan_names.get(vlan_id)
            if vlan_name:
                vlans_map[vlan_id]["names"].add(vlan_name)

    # 2. Add port mappings grouped by switch
    for switch in switches:
        for port in switch.ports:
            vlan_ids = []
            access_vlan = port.get("access_vlan")
            if isinstance(access_vlan, int):
                vlan_ids.append(access_vlan)
            native_vlan = port.get("native_vlan")
            if isinstance(native_vlan, int):
                vlan_ids.append(native_vlan)
            for key in ("allowed_vlans", "hybrid_allowed_vlans"):
                vals = port.get(key)
                if isinstance(vals, list):
                    for v in vals:
                        if isinstance(v, int):
                            vlan_ids.append(v)
            
            for vlan_id in set(vlan_ids):
                if vlan_id not in vlans_map:
                    vlans_map[vlan_id] = {
                        "id": vlan_id,
                        "names": set(),
                        "switches": {}
                    }
                
                if switch.slug not in vlans_map[vlan_id]["switches"]:
                    vlans_map[vlan_id]["switches"][switch.slug] = {
                        "hostname": switch.hostname,
                        "slug": switch.slug,
                        "ports": []
                    }
                
                vlans_map[vlan_id]["switches"][switch.slug]["ports"].append({
                    "name": port.get("name"),
                    "mode": port.get("mode"),
                    "description": port.get("description", "")
                })

    # 3. Format and serialize the map
    vlans_list = []
    for vlan_id, data in vlans_map.items():
        names = sorted(list(data["names"]))
        vlan_name_str = ", ".join(names) if names else f"VLAN {vlan_id}"
        
        switches_list = []
        total_ports_count = 0
        for switch_slug, sdata in data["switches"].items():
            ports_list = sorted(sdata["ports"], key=lambda x: x["name"])
            total_ports_count += len(ports_list)
            switches_list.append({
                "hostname": sdata["hostname"],
                "slug": sdata["slug"],
                "ports": ports_list,
                "ports_count": len(ports_list)
            })
            
        switches_list.sort(key=lambda x: x["hostname"].lower())
        
        vlans_list.append({
            "id": vlan_id,
            "name": vlan_name_str,
            "switches": switches_list,
            "ports_count": total_ports_count
        })
        
    vlans_list.sort(key=lambda x: x["id"])
    
    total_vlans = len(vlans_list)
    most_used_vlan = None
    max_ports = -1
    for v in vlans_list:
        if v["ports_count"] > max_ports:
            max_ports = v["ports_count"]
            most_used_vlan = {
                "id": v["id"],
                "name": v["name"],
                "ports_count": v["ports_count"]
            }
            
    from datetime import datetime
    last_updated = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    return {
        "total_vlans": total_vlans,
        "most_used_vlan": most_used_vlan,
        "last_updated": last_updated,
        "vlans": vlans_list
    }


@app.get("/vlans", response_class=HTMLResponse)
def vlans_dashboard(
    request: Request,
    repository: JsonInventoryRepository = Depends(get_repository),
) -> HTMLResponse:
    """Aggregated VLAN inventory dashboard using cached data."""
    cache_path = settings.BASE_DIR / "data" / "vlans_cache.json"
    
    if not cache_path.exists():
        data = aggregate_vlans_data(repository)
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            cache_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass
    else:
        try:
            data = json.loads(cache_path.read_text(encoding="utf-8"))
        except Exception:
            data = aggregate_vlans_data(repository)
            try:
                cache_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            except Exception:
                pass

    total_vlans = data.get("total_vlans", 0)
    most_used_vlan = data.get("most_used_vlan")
    vlans_list = data.get("vlans", [])
    last_updated = data.get("last_updated", "-")
    
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
            "last_updated": last_updated,
        },
    )


@app.post("/api/vlans/refresh")
def refresh_vlans_cache(
    repository: JsonInventoryRepository = Depends(get_repository),
):
    """Force manual regeneration of the VLANs cache."""
    cache_path = settings.BASE_DIR / "data" / "vlans_cache.json"
    data = aggregate_vlans_data(repository)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        cache_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to write cache: {str(e)}")
    return {"status": "success", "last_updated": data["last_updated"]}


@app.get("/switches/{slug}", response_class=HTMLResponse)
async def switch_detail(
    request: Request,
    slug: str,
    repository: JsonInventoryRepository = Depends(get_repository),
) -> HTMLResponse:
    switch = repository.get_switch(slug)
    if switch is None:
        raise HTTPException(status_code=404, detail="Switch not found")

    cfg_filename = switch.source_file.replace('.json', '.cfg')
    history = get_file_history(settings.BACKUPS_GIT_DIR, cfg_filename)

    ox_nodes = await get_oxidized_nodes()
    ox_status = None
    for n in ox_nodes:
        if n.get("name", "").lower() == switch.hostname.lower() or n.get("ip") == switch.ip:
            ox_status = n
            break

    return templates.TemplateResponse(
        request,
        "switch_detail.html",
        {
            "active_page": "inventory",
            "switch": switch,
            "history": history,
            "oxidized_status": ox_status,
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


@app.get("/oxidized", response_class=HTMLResponse)
def oxidized_page(
    request: Request,
    repository: JsonInventoryRepository = Depends(get_repository),
) -> HTMLResponse:
    """Render the Oxidized status page."""
    return templates.TemplateResponse(
        request,
        "oxidized.html",
        {
            "active_page": "oxidized",
        },
    )


@app.get("/api/oxidized/status")
async def api_oxidized_status(
    repository: JsonInventoryRepository = Depends(get_repository),
):
    """API endpoint returning real-time Oxidized backup status combined with Git details."""
    nodes = await get_oxidized_nodes()
    switches = repository.list_switches()

    oxidized_map = {}
    for node in nodes:
        name = node.get("name")
        ip = node.get("ip")
        if name:
            oxidized_map[name.lower()] = node
        if ip:
            oxidized_map[ip] = node

    status_list = []
    for switch in switches:
        ox_node = oxidized_map.get(switch.hostname.lower()) or oxidized_map.get(switch.ip)
        status = "unknown"
        message = None
        mtime = None

        if ox_node:
            status = ox_node.get("status", "unknown")
            message = ox_node.get("message")
            mtime = ox_node.get("mtime")

        cfg_filename = switch.source_file.replace(".json", ".cfg")
        last_commit = get_last_commit_for_file(settings.BACKUPS_GIT_DIR, cfg_filename)

        status_list.append({
            "hostname": switch.hostname,
            "slug": switch.slug,
            "ip": switch.ip,
            "status": status,
            "message": message,
            "mtime": mtime,
            "last_commit": last_commit
        })

    return {
        "oxidized_connected": len(nodes) > 0,
        "last_sync": get_last_global_backup_time(settings.BACKUPS_GIT_DIR),
        "nodes": status_list
    }



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
            
        # Delete VLANs cache to force regeneration
        cache_path = settings.BASE_DIR / "data" / "vlans_cache.json"
        if cache_path.exists():
            try:
                cache_path.unlink()
            except Exception:
                pass
                
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




