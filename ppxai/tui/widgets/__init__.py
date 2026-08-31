"""
ppxaide widgets - Custom Textual widgets for the TUI.
"""

from ppxai.tui.widgets.base import SafeQueryMixin
from ppxai.tui.widgets.chat_view import ChatView
from ppxai.tui.widgets.code_editor import CodeEditor
from ppxai.tui.widgets.data_viewer import DataViewer
from ppxai.tui.widgets.dialog import ConsentDialog, MessageDialog, PromptDialog
from ppxai.tui.widgets.image_viewer import ImageViewer
from ppxai.tui.widgets.input_box import InputBox
from ppxai.tui.widgets.message_box import MessageBox
from ppxai.tui.widgets.side_panel import SidePanel
from ppxai.tui.widgets.split_pane import HorizontalSplit, Pane, SplitPane, VerticalSplit
from ppxai.tui.widgets.status_bar import StatusBar
from ppxai.tui.widgets.table_viewer import TableViewer
from ppxai.tui.widgets.tree_viewer import TreeViewer

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
    "DataViewer",
    "ImageViewer",
    "TableViewer",
    "SplitPane",
    "Pane",
    "HorizontalSplit",
    "VerticalSplit",
    "SidePanel",
    # Dialogs
    "ConsentDialog",
    "PromptDialog",
    "MessageDialog",
]
