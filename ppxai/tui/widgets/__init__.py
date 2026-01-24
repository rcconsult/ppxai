"""
ppxaide widgets - Custom Textual widgets for the TUI.
"""

from ppxai.tui.widgets.base import SafeQueryMixin
from ppxai.tui.widgets.status_bar import StatusBar
from ppxai.tui.widgets.chat_view import ChatView
from ppxai.tui.widgets.input_box import InputBox
from ppxai.tui.widgets.message_box import MessageBox
from ppxai.tui.widgets.tree_viewer import TreeViewer
from ppxai.tui.widgets.code_editor import CodeEditor
from ppxai.tui.widgets.split_pane import SplitPane, Pane, HorizontalSplit, VerticalSplit
from ppxai.tui.widgets.side_panel import SidePanel

__all__ = [
    # Base classes
    "SafeQueryMixin",
    # Widgets
    "StatusBar",
    "ChatView",
    "InputBox",
    "MessageBox",
    "TreeViewer",
    "CodeEditor",
    "SplitPane",
    "Pane",
    "HorizontalSplit",
    "VerticalSplit",
    "SidePanel",
]
