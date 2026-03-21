"""
Visual constants for ppxai-native — catppuccin-mocha default theme.
"""

import pyray as rl


# Catppuccin Mocha palette
BG = rl.Color(30, 30, 46, 255)
STATUS_BG = rl.Color(24, 24, 37, 255)
INPUT_BG = rl.Color(36, 36, 54, 255)
USER_BUBBLE = rl.Color(45, 45, 65, 255)
AI_BUBBLE = rl.Color(35, 35, 52, 255)
TOOL_BUBBLE = rl.Color(30, 35, 50, 255)
CODE_BG = rl.Color(24, 24, 37, 255)
TEXT = rl.Color(205, 214, 244, 255)
TEXT_DIM = rl.Color(147, 153, 178, 255)
TEXT_SYSTEM = rl.Color(166, 173, 200, 255)
ACCENT = rl.Color(137, 180, 250, 255)       # blue
USER_ACCENT = rl.Color(166, 227, 161, 255)  # green
TOOL_ACCENT = rl.Color(250, 179, 135, 255)  # peach
ERROR = rl.Color(243, 139, 168, 255)        # red
CURSOR = rl.Color(245, 224, 220, 255)       # rosewater
SCROLLBAR = rl.Color(88, 91, 112, 128)
SCROLLBAR_HOVER = rl.Color(88, 91, 112, 200)
SELECTION = rl.Color(137, 180, 250, 60)
BORDER = rl.Color(69, 71, 90, 255)

# Font sizes
FONT_SIZE = 18
FONT_SIZE_SMALL = 14
FONT_SIZE_STATUS = 14
LINE_HEIGHT = FONT_SIZE + 4
LINE_HEIGHT_SMALL = FONT_SIZE_SMALL + 3

# Spacing
PADDING = 12
PADDING_SMALL = 6
STATUS_HEIGHT = 32
INPUT_MIN_HEIGHT = 80
INPUT_MAX_HEIGHT = 200
MESSAGE_GAP = 8
SCROLLBAR_WIDTH = 8

# Window
DEFAULT_WIDTH = 1280
DEFAULT_HEIGHT = 800
MIN_WIDTH = 600
MIN_HEIGHT = 400
TARGET_FPS = 60
