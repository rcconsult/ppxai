"""
Provider and model management endpoints.
"""

from fastapi import APIRouter, Header, HTTPException
from typing import Optional

from ..models import SetProviderRequest, SetModelRequest, ToolsRequest, ToolsConfigRequest
from ..state import get_or_create_session
from ...common.logger import get_logger

logger = get_logger("server")

router = APIRouter()


@router.get("/providers")
async def get_providers(x_session_id: Optional[str] = Header(None)):
    """Get list of available providers.

    v1.13.10: Supports X-Session-Id header for session isolation.
    """
    session_id, engine, _ = await get_or_create_session(x_session_id)

    # Reload config to pick up external changes (e.g., new providers added)
    engine.reload_config()

    providers = engine.list_providers()
    return {
        "providers": [
            {
                "id": p.id,
                "name": p.name,
                "has_api_key": p.has_api_key,
                "default_model": p.default_model,
                "capabilities": {
                    "web_search": p.capabilities.web_search,
                    "citations": p.capabilities.citations,
                    "streaming": p.capabilities.streaming,
                }
            }
            for p in providers
        ],
        "current": engine.provider_name,
    }


@router.post("/providers")
async def set_provider(
    request: SetProviderRequest,
    x_session_id: Optional[str] = Header(None)
):
    """Set the active provider.

    v1.13.10: Supports X-Session-Id header for session isolation.
    """
    session_id, engine, _ = await get_or_create_session(x_session_id)

    # Reload config to pick up external changes before switching
    engine.reload_config()

    success = engine.set_provider(request.provider)
    if not success:
        raise HTTPException(status_code=400, detail=f"Failed to set provider: {request.provider}")

    # Optionally set model
    if request.model:
        engine.set_model(request.model, reset_context=request.reset_context)

    result = {
        "provider": engine.provider_name,
        "model": engine.model,
    }
    if engine.last_model_switch_reset > 0:
        result["context_reset"] = engine.last_model_switch_reset
    return result


@router.get("/models")
async def get_models(x_session_id: Optional[str] = Header(None)):
    """Get list of models for current provider.

    v1.13.10: Supports X-Session-Id header for session isolation.
    """
    session_id, engine, _ = await get_or_create_session(x_session_id)

    # Reload config to pick up external changes (e.g., new models added)
    engine.reload_config()

    models = engine.list_models()
    return {
        "models": [
            {
                "id": m.id,
                "name": m.name,
                "description": m.description,
            }
            for m in models
        ],
        "current": engine.model,
        "provider": engine.provider_name,
    }


@router.post("/models")
async def set_model(
    request: SetModelRequest,
    x_session_id: Optional[str] = Header(None)
):
    """Set the active model.

    v1.13.10: Supports X-Session-Id header for session isolation.
    """
    session_id, engine, _ = await get_or_create_session(x_session_id)

    # Reload config to pick up external changes before switching
    engine.reload_config()

    success = engine.set_model(request.model, reset_context=request.reset_context)
    if not success:
        raise HTTPException(status_code=400, detail=f"Failed to set model: {request.model}")

    result = {
        "model": engine.model,
        "provider": engine.provider_name,
    }
    if engine.last_model_switch_reset > 0:
        result["context_reset"] = engine.last_model_switch_reset
    return result


# === Tools Management ===

@router.get("/tools")
async def get_tools(x_session_id: Optional[str] = Header(None)):
    """Get list of available tools.

    v1.13.10: Supports X-Session-Id header for session isolation.
    """
    session_id, engine, _ = await get_or_create_session(x_session_id)

    tools = engine.list_tools()

    # Get consent mode from session (v1.11.9)
    consent_mode = "default"
    try:
        if hasattr(engine, 'session') and hasattr(engine.session, 'edit_consent_mode'):
            consent_mode = engine.session.edit_consent_mode
    except Exception as e:
        logger.debug(f"Failed to get consent mode from session: {e}")

    # Get full status including auto_retry_empty
    status = engine.get_tools_status()

    return {
        "tools": tools,  # Already list of {"name": ..., "description": ...}
        "enabled": engine.tools_enabled,
        "max_iterations": status.get('max_iterations', 15),
        "auto_retry_empty": status.get('auto_retry_empty', 2),
        "consent_mode": consent_mode,
        "verbose": status.get('verbose', False),
    }


@router.post("/tools")
async def set_tools(
    request: ToolsRequest,
    x_session_id: Optional[str] = Header(None)
):
    """Enable or disable tools.

    v1.13.10: Supports X-Session-Id header for session isolation.
    """
    session_id, engine, _ = await get_or_create_session(x_session_id)

    if request.enabled:
        engine.enable_tools()
    else:
        engine.disable_tools()

    return {
        "enabled": engine.tools_enabled,
    }


@router.post("/tools/config")
async def set_tools_config(
    request: ToolsConfigRequest,
    x_session_id: Optional[str] = Header(None)
):
    """Configure tool settings (e.g., max_iterations).

    v1.13.10: Supports X-Session-Id header for session isolation.
    """
    session_id, engine, _ = await get_or_create_session(x_session_id)

    success = engine.set_tool_config(request.setting, request.value)
    if not success:
        raise HTTPException(status_code=400, detail=f"Unknown setting: {request.setting}")

    return {
        "setting": request.setting,
        "value": request.value,
        "success": True,
    }


@router.get("/tools/help/{tool_name}")
async def get_tool_help(
    tool_name: str,
    x_session_id: Optional[str] = Header(None)
):
    """Get detailed help for a specific tool.

    Returns tool definition including parameters, description, and usage examples.

    v1.13.10: Supports X-Session-Id header for session isolation.
    """
    session_id, engine, _ = await get_or_create_session(x_session_id)

    if not engine.tools_enabled or not engine.tool_manager:
        raise HTTPException(status_code=400, detail="Tools not enabled")

    tool = engine.tool_manager.get_tool(tool_name)
    if not tool:
        available_tools = engine.tool_manager.list_tools()
        tool_names = [t['name'] for t in available_tools]
        raise HTTPException(
            status_code=404,
            detail=f"Tool not found: {tool_name}. Available: {', '.join(sorted(tool_names))}"
        )

    tool_info = tool.get_definition()
    return {
        "name": tool_name,
        "description": tool_info.get("function", {}).get("description", ""),
        "parameters": tool_info.get("function", {}).get("parameters", {}),
    }
