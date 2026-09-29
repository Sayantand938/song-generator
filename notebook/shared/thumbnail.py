import os
from PIL import Image, ImageDraw, ImageFont

try:
    from titlecase_util import to_title_case
except ImportError:
    from shared.titlecase_util import to_title_case


VIDEO_WIDTH = 1920
VIDEO_HEIGHT = 1080

# Prefer JetBrains Mono (downloaded by s01_setup.py to /kaggle/working/fonts/)
FONT_CANDIDATES = [
    "/kaggle/working/fonts/JetBrainsMono-Bold.ttf",
    "/kaggle/working/fonts/JetBrainsMono-Regular.ttf",
    "/usr/share/fonts/truetype/jetbrains-mono/JetBrainsMono-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
]


def _get_font(size):
    for c in FONT_CANDIDATES:
        if os.path.exists(c):
            try:
                return ImageFont.truetype(c, size)
            except Exception:
                continue
    return ImageFont.load_default()


def create_thumbnail(slug: str, output_path: str) -> None:
    img = Image.new("RGB", (VIDEO_WIDTH, VIDEO_HEIGHT), (0, 0, 0))
    draw = ImageDraw.Draw(img)
    display_title = to_title_case(slug)
    words = display_title.split()

    chosen_lines, chosen_font, chosen_bboxes, chosen_heights, chosen_spacing = \
        [display_title], _get_font(40), [], [], 14

    for font_size in range(88, 38, -4):
        font = _get_font(font_size)
        lines, cur_line, overflow = [], [], False
        for word in words:
            test_line = " ".join(cur_line + [word])
            bbox = draw.textbbox((0, 0), test_line, font=font)
            if bbox[2] - bbox[0] <= 1520:
                cur_line.append(word)
            else:
                if not cur_line:
                    overflow = True
                    break
                lines.append(" ".join(cur_line))
                cur_line = [word]
        if cur_line:
            lines.append(" ".join(cur_line))
        if overflow or len(lines) > 3:
            continue

        spacing = int(font_size * 0.35)
        bboxes = [draw.textbbox((0, 0), l, font=font) for l in lines]
        heights = [b[3] - b[1] for b in bboxes]
        if sum(heights) + (len(lines) - 1) * spacing <= 730:
            chosen_lines, chosen_font = lines, font
            chosen_bboxes, chosen_heights, chosen_spacing = bboxes, heights, spacing
            break

    total_h = sum(chosen_heights) + (len(chosen_lines) - 1) * chosen_spacing
    cur_y = (VIDEO_HEIGHT - total_h) // 2
    for i, line in enumerate(chosen_lines):
        line_w = chosen_bboxes[i][2] - chosen_bboxes[i][0] if chosen_bboxes else 0
        draw.text(((VIDEO_WIDTH - line_w) // 2, cur_y), line, font=chosen_font, fill=(255, 255, 255))
        cur_y += chosen_heights[i] + chosen_spacing

    img.save(output_path, "PNG", optimize=True)