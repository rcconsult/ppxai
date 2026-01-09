"""Create TUI icon with pixel-perfect >_ symbol."""
from PIL import Image, ImageDraw

original = Image.open('resources/ppxai.ico')
sizes = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]

original_frames = []
for size in sizes:
    frame = original.copy()
    frame = frame.resize(size, Image.Resampling.LANCZOS)
    original_frames.append((size, frame))

def create_tui_icon_sharp(img, size):
    """Create TUI icon with very sharp >_ symbol using pixel-perfect lines."""
    img = img.copy().convert('RGBA')
    draw = ImageDraw.Draw(img)

    bubble_color = (108, 92, 231, 255)  # Purple
    center_x = size[0] // 2
    center_y = int(size[1] * 0.42)

    # Cover dots area
    dot_area_width = int(size[0] * 0.75)
    dot_area_height = int(size[1] * 0.40)
    x1 = center_x - dot_area_width // 2
    y1 = center_y - dot_area_height // 2
    x2 = center_x + dot_area_width // 2
    y2 = center_y + dot_area_height // 2
    draw.rectangle([x1, y1, x2, y2], fill=bubble_color)

    white = (255, 255, 255, 255)
    w = size[0]

    # Line width proportional to icon size
    lw = max(2, w // 8)

    # Draw > as two lines meeting at a point
    # > starts at left, goes right-down, then right-up
    gt_left = w // 4
    gt_right = w // 2
    gt_top = int(w * 0.32)
    gt_mid = int(w * 0.44)
    gt_bot = int(w * 0.56)

    draw.line([(gt_left, gt_top), (gt_right, gt_mid)], fill=white, width=lw)
    draw.line([(gt_right, gt_mid), (gt_left, gt_bot)], fill=white, width=lw)

    # Draw _ as horizontal line
    us_left = int(w * 0.56)
    us_right = int(w * 0.75)
    us_y = gt_bot

    draw.line([(us_left, us_y), (us_right, us_y)], fill=white, width=lw)

    return img

new_frames = []
for size, frame in original_frames:
    new_frame = create_tui_icon_sharp(frame, size)
    new_frames.append(new_frame)

new_frames[0].save(
    'resources/ppxai-tui.ico',
    format='ICO',
    sizes=sizes,
    append_images=new_frames[1:]
)

print('Created sharp TUI icon: resources/ppxai-tui.ico')
