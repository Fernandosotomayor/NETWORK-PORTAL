"""FastAPI web MVP for normalized Planet switch JSON files."""

from __future__ import annotations

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .core.config import settings
from .repository import JsonInventoryRepository, compact_vlan_list
from .services.audit import generate_global_report
from .services.git_history import get_file_diff, get_file_history, get_recent_changes
from .services.topology import generate_topology, TopologyState, load_topology_state, save_topology_state

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




