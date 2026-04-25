"""
Provider and model management endpoints.
"""

from fastapi import APIRouter, Depends, HTTPException

from ..models import SetProviderRequest, SetModelRequest, ToolsRequest, ToolsConfigRequest
from ..state import Session, get_session, with_drained_events
from ...common.logger import get_logger
from ...constants import Default

logger = get_logger("server")

router = APIRouter()


@router.get("/providers")
async def get_providers(s: Session = Depends(get_session)):
    """Get list of available providers."""
    providers = s.engine.list_providers()
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
        "current": s.engine.state.get("provider"),
    }


@router.post("/providers")
async def set_provider(request: SetProviderRequest, s: Session = Depends(get_session)):
    """Set the active provider."""
    success = s.engine.set_provider(request.provider)
    if not success:
        raise HTTPException(status_code=400, detail=f"Failed to set provider: {request.provider}")

    if request.model:
        s.engine.set_model(request.model, reset_context=request.reset_context)

    state = s.engine.state
    result = {
        "provider": state.get("provider"),
        "model": state.get("model"),
    }
    if s.engine.last_model_switch_reset > 0:
        result["context_reset"] = s.engine.last_model_switch_reset
    return with_drained_events(result, s.engine)


@router.get("/models")
async def get_models(s: Session = Depends(get_session)):
    """Get list of models for current provider."""
    models = s.engine.list_models()
    state = s.engine.state
    return {
        "models": [
            {
                "id": m.id,
                "name": m.name,
                "description": m.description,
            }
            for m in models
        ],
        "current": state.get("model"),
        "provider": state.get("provider"),
    }


@router.post("/models")
async def set_model(request: SetModelRequest, s: Session = Depends(get_session)):
    """Set the active model."""
    success = s.engine.set_model(request.model, reset_context=request.reset_context)
    if not success:
        raise HTTPException(status_code=400, detail=f"Failed to set model: {request.model}")

    state = s.engine.state
    result = {
        "model": state.get("model"),
        "provider": state.get("provider"),
    }
    if s.engine.last_model_switch_reset > 0:
        result["context_reset"] = s.engine.last_model_switch_reset
    return with_drained_events(result, s.engine)


# === Tools Management ===

@router.get("/tools")
async def get_tools(s: Session = Depends(get_session)):
    """Get list of available tools."""
    tools = s.engine.list_tools()

    consent_mode = "default"
    try:
        if hasattr(s.engine, 'session') and hasattr(s.engine.session, 'edit_consent_mode'):
            consent_mode = s.engine.session.edit_consent_mode
    except Exception as e:
        logger.debug(f"Failed to get consent mode from session: {e}")

    status = s.engine.get_tools_status()

    return {
        "tools": tools,
        "enabled": s.engine.state.get("tools_enabled"),
        "max_iterations": status.get('max_iterations', Default.MAX_TOOL_ITERATIONS),
        "auto_retry_empty": status.get('auto_retry_empty', Default.AUTO_RETRY_EMPTY),
        "consent_mode": consent_mode,
        "verbose": status.get('verbose', False),
    }


@router.post("/tools")
async def set_tools(request: ToolsRequest, s: Session = Depends(get_session)):
    """Enable or disable tools."""
    if request.enabled:
        s.engine.enable_tools()
    else:
        s.engine.disable_tools()

    return with_drained_events(
        {"enabled": s.engine.state.get("tools_enabled")},
        s.engine,
    )


@router.post("/tools/config")
async def set_tools_config(request: ToolsConfigRequest, s: Session = Depends(get_session)):
    """Configure tool settings (e.g., max_iterations)."""
    success = s.engine.set_tool_config(request.setting, request.value)
    if not success:
        raise HTTPException(status_code=400, detail=f"Unknown setting: {request.setting}")

    return with_drained_events(
        {
            "setting": request.setting,
            "value": request.value,
            "success": True,
        },
        s.engine,
    )


@router.get("/tools/help/{tool_name}")
async def get_tool_help(tool_name: str, s: Session = Depends(get_session)):
    """Get detailed help for a specific tool."""
    if not s.engine.state.get("tools_enabled") or not s.engine.tool_manager:
        raise HTTPException(status_code=400, detail="Tools not enabled")

    tool = s.engine.tool_manager.get_tool(tool_name)
    if not tool:
        available_tools = s.engine.tool_manager.list_tools()
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
