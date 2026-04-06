"""
Built-in tools for the ppxai engine.

These tools are registered automatically when the engine starts.
"""

from typing import Optional

from . import filesystem, calculator, datetime_tool, web
from ...types import ToolEngineProtocol, ToolManagerProtocol


def register_all_builtin_tools(manager: ToolManagerProtocol, provider: str = None, engine: Optional[ToolEngineProtocol] = None):
    """Register all built-in tools with the manager.

    Args:
        manager: ToolManager instance
        provider: Current provider name (for capability-based filtering)
        engine: Engine client instance (required for file editing and shell tools v1.11.0+)
    """

    # Register tools from each module
    filesystem.register_tools(manager, engine)
    calculator.register_tools(manager)
    datetime_tool.register_tools(manager)

    # Web search: Try premium first (v1.13.4), fall back to free
    try:
        from . import web_premium
        if web_premium.is_available():
            web_premium.register_tools(manager, provider)
        else:
            web.register_tools(manager, provider)
    except Exception:
        # Fall back to free search if premium module fails
        web.register_tools(manager, provider)

    # Register tools that require engine for consent (v1.11.0+)
    if engine is not None:
        try:
            from . import editor, shell
            editor.register_tools(manager, engine)
            shell.register_tools(manager, engine)
        except Exception:
            # Silently skip if consent-based tools fail to register
            pass

        # Container management tools (v1.13.8)
        try:
            from . import container
            container.register_tools(manager, engine)
        except Exception:
            # Silently skip if container tools fail to register
            pass

        # Display tools (v1.15.1)
        try:
            from . import display
            display.register_tools(manager, engine)
        except Exception:
            # Silently skip if display tools fail to register
            pass

        # PDF tools (v1.17.4 Phase 2.8) — read_pdf, get_pdf_page_image.
        # Guarded by a pypdf import inside `register_tools`, which
        # returns False without raising if the [data] extras group is
        # missing. The try/except here catches any unexpected failures
        # (e.g., file_store wiring broken) so a PDF tool bug can never
        # block the whole engine from starting up.
        try:
            from . import pdf_tools
            pdf_tools.register_tools(manager, engine)
        except Exception:
            pass

        # Excel tools (v1.17.4 Phase 4.1) — list_excel_sheets, read_excel_sheet.
        try:
            from . import excel_tools
            excel_tools.register_tools(manager, engine)
        except Exception:
            pass

        # PowerPoint tools (v1.17.4 Phase 4.2) — list_pptx_slides, read_pptx_slide_text.
        try:
            from . import pptx_tools
            pptx_tools.register_tools(manager, engine)
        except Exception:
            pass
