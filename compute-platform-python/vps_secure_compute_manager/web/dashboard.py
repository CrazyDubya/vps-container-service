"""
VPS Secure Compute Manager - Web Dashboard
Production-ready web interface for container management
"""

import os
import json
import asyncio
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional
from pathlib import Path

from fastapi import FastAPI, Request, Form, HTTPException, Depends, status
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import aiofiles

# Dashboard app
dashboard = FastAPI(
    title="VPS Secure Compute Dashboard",
    description="Web interface for VPS Secure Compute Manager"
)

# Templates and static files
templates_dir = Path(__file__).parent / "templates"
static_dir = Path(__file__).parent / "static"

templates_dir.mkdir(exist_ok=True)
static_dir.mkdir(exist_ok=True)

templates = Jinja2Templates(directory=str(templates_dir))
dashboard.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

# Security
security = HTTPBearer(auto_error=False)

# Global state (will be injected from main app)
app_state = None

def set_app_state(state):
    """Set the application state"""
    global app_state
    app_state = state

async def get_current_user_web(request: Request, credentials: HTTPAuthorizationCredentials = Depends(security)):
    """Get current user for web interface"""
    # Check session cookie first
    token = request.cookies.get("access_token")
    
    # Fall back to Authorization header
    if not token and credentials:
        token = credentials.credentials
    
    if not token:
        return None
    
    try:
        payload = app_state.auth_manager.verify_jwt_token(token)
        
        with app_state.db_manager.get_session() as session:
            from ..iam.models import User
            user = session.query(User).filter(User.id == payload["user_id"]).first()
            
            if not user or not user.is_active:
                return None
            
            return {
                "user_id": user.id,
                "tenant_id": user.tenant_id,
                "email": user.email,
                "role": user.role,
                "name": user.email.split("@")[0]  # Simple name extraction
            }
    
    except Exception:
        return None

@dashboard.get("/", response_class=HTMLResponse)
async def dashboard_home(request: Request, current_user: dict = Depends(get_current_user_web)):
    """Dashboard home page"""
    if not current_user:
        return RedirectResponse(url="/login", status_code=302)
    
    # Get dashboard stats
    try:
        # Get containers
        containers = await app_state.firecracker_backend.list_containers(
            tenant_id=current_user["tenant_id"]
        )
        
        # Get volumes
        volumes = app_state.storage_manager.list_volumes(tenant_id=current_user["tenant_id"])
        
        # Get networks
        networks = app_state.network_manager.list_networks(tenant_id=current_user["tenant_id"])
        
        # Calculate stats
        stats = {
            "containers": {
                "total": len(containers),
                "running": len([c for c in containers if c.status.value == "running"]),
                "stopped": len([c for c in containers if c.status.value == "stopped"])
            },
            "volumes": {
                "total": len(volumes),
                "total_size_gb": sum(v.get("size_gb", 0) for v in volumes)
            },
            "networks": {
                "total": len(networks)
            }
        }
        
        return templates.TemplateResponse("dashboard.html", {
            "request": request,
            "user": current_user,
            "stats": stats,
            "containers": containers[:5],  # Recent 5
            "recent_activity": []  # Would get from audit logs
        })
        
    except Exception as e:
        return templates.TemplateResponse("error.html", {
            "request": request,
            "error": f"Failed to load dashboard: {str(e)}"
        })

@dashboard.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    """Login page"""
    return templates.TemplateResponse("login.html", {"request": request})

@dashboard.post("/login")
async def login_submit(request: Request, email: str = Form(...), password: str = Form(...)):
    """Handle login form submission"""
    try:
        with app_state.db_manager.get_session() as session:
            auth_result = app_state.auth_manager.authenticate_user(
                session, email, password, ip_address=request.client.host
            )
            
            response = RedirectResponse(url="/", status_code=302)
            response.set_cookie(
                key="access_token",
                value=auth_result["jwt_token"],
                max_age=3600,
                httponly=True,
                secure=True,  # HTTPS only in production
                samesite="strict"
            )
            
            return response
    
    except Exception as e:
        return templates.TemplateResponse("login.html", {
            "request": request,
            "error": "Invalid credentials"
        })

@dashboard.post("/logout")
async def logout(request: Request):
    """Logout"""
    response = RedirectResponse(url="/login", status_code=302)
    response.delete_cookie("access_token")
    return response

@dashboard.get("/containers", response_class=HTMLResponse)
async def containers_page(request: Request, current_user: dict = Depends(get_current_user_web)):
    """Containers management page"""
    if not current_user:
        return RedirectResponse(url="/login", status_code=302)
    
    try:
        containers = await app_state.firecracker_backend.list_containers(
            tenant_id=current_user["tenant_id"]
        )
        
        # Also get LXC containers
        try:
            lxc_containers = await app_state.lxc_backend.list_containers(
                tenant_id=current_user["tenant_id"]
            )
            containers.extend(lxc_containers)
        except:
            pass
        
        templates_list = app_state.template_manager.list_available_templates()
        
        return templates.TemplateResponse("containers.html", {
            "request": request,
            "user": current_user,
            "containers": containers,
            "templates": templates_list
        })
        
    except Exception as e:
        return templates.TemplateResponse("error.html", {
            "request": request,
            "error": f"Failed to load containers: {str(e)}"
        })

@dashboard.post("/containers/create")
async def create_container_web(
    request: Request,
    current_user: dict = Depends(get_current_user_web),
    name: str = Form(...),
    template: str = Form(...),
    memory_mb: int = Form(...),
    cpu_count: int = Form(...),
    storage_gb: float = Form(...)
):
    """Create container from web form"""
    if not current_user:
        return RedirectResponse(url="/login", status_code=302)
    
    try:
        from ..backends.base import ContainerConfig
        
        config = ContainerConfig(
            name=name,
            template=template,
            memory_mb=memory_mb,
            cpu_count=cpu_count,
            storage_gb=storage_gb,
            gpu_count=0,
            network_config={"networks": ["default"]},
            security_config={},
            environment={},
            volumes=[],
            user_context=current_user
        )
        
        container_id = await app_state.firecracker_backend.create_container(config)
        
        return RedirectResponse(url="/containers", status_code=302)
        
    except Exception as e:
        return RedirectResponse(url=f"/containers?error={str(e)}", status_code=302)

@dashboard.get("/volumes", response_class=HTMLResponse)
async def volumes_page(request: Request, current_user: dict = Depends(get_current_user_web)):
    """Volumes management page"""
    if not current_user:
        return RedirectResponse(url="/login", status_code=302)
    
    try:
        volumes = app_state.storage_manager.list_volumes(tenant_id=current_user["tenant_id"])
        
        return templates.TemplateResponse("volumes.html", {
            "request": request,
            "user": current_user,
            "volumes": volumes
        })
        
    except Exception as e:
        return templates.TemplateResponse("error.html", {
            "request": request,
            "error": f"Failed to load volumes: {str(e)}"
        })

@dashboard.get("/networks", response_class=HTMLResponse)
async def networks_page(request: Request, current_user: dict = Depends(get_current_user_web)):
    """Networks management page"""
    if not current_user:
        return RedirectResponse(url="/login", status_code=302)
    
    try:
        networks = app_state.network_manager.list_networks(tenant_id=current_user["tenant_id"])
        
        return templates.TemplateResponse("networks.html", {
            "request": request,
            "user": current_user,
            "networks": networks
        })
        
    except Exception as e:
        return templates.TemplateResponse("error.html", {
            "request": request,
            "error": f"Failed to load networks: {str(e)}"
        })

@dashboard.get("/templates", response_class=HTMLResponse)
async def templates_page(request: Request, current_user: dict = Depends(get_current_user_web)):
    """Templates page"""
    if not current_user:
        return RedirectResponse(url="/login", status_code=302)
    
    try:
        available_templates = app_state.template_manager.list_available_templates()
        installed_templates = app_state.template_manager.list_installed_templates()
        
        return templates.TemplateResponse("templates.html", {
            "request": request,
            "user": current_user,
            "available_templates": available_templates,
            "installed_templates": installed_templates
        })
        
    except Exception as e:
        return templates.TemplateResponse("error.html", {
            "request": request,
            "error": f"Failed to load templates: {str(e)}"
        })

@dashboard.get("/monitoring", response_class=HTMLResponse)
async def monitoring_page(request: Request, current_user: dict = Depends(get_current_user_web)):
    """Monitoring and metrics page"""
    if not current_user:
        return RedirectResponse(url="/login", status_code=302)
    
    return templates.TemplateResponse("monitoring.html", {
        "request": request,
        "user": current_user
    })

# API endpoints for AJAX calls
@dashboard.get("/api/containers/{container_id}/metrics")
async def get_container_metrics(
    container_id: str,
    current_user: dict = Depends(get_current_user_web)
):
    """Get container metrics for dashboard"""
    if not current_user:
        raise HTTPException(status_code=401, detail="Unauthorized")
    
    try:
        # Try both backends
        try:
            metrics = await app_state.firecracker_backend.get_metrics(container_id)
        except:
            metrics = await app_state.lxc_backend.get_metrics(container_id)
        
        return metrics
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@dashboard.post("/api/containers/{container_id}/action")
async def container_action(
    container_id: str,
    request: Request,
    current_user: dict = Depends(get_current_user_web)
):
    """Perform action on container"""
    if not current_user:
        raise HTTPException(status_code=401, detail="Unauthorized")
    
    try:
        data = await request.json()
        action = data.get("action")
        
        # Get backend for container
        backend = None
        try:
            container_info = await app_state.firecracker_backend.get_container_info(container_id)
            backend = app_state.firecracker_backend
        except:
            container_info = await app_state.lxc_backend.get_container_info(container_id)
            backend = app_state.lxc_backend
        
        if not container_info or container_info.tenant_id != current_user["tenant_id"]:
            raise HTTPException(status_code=404, detail="Container not found")
        
        success = False
        if action == "start":
            success = await backend.start_container(container_id)
        elif action == "stop":
            success = await backend.stop_container(container_id)
        elif action == "restart":
            await backend.stop_container(container_id)
            success = await backend.start_container(container_id)
        elif action == "delete":
            success = await backend.destroy_container(container_id)
        
        return {"success": success}
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))