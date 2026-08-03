"""
Renders the /me profile card as a single PNG image, combining:
- the character's Lodestone portrait (left side)
- the requesting/target Discord user's avatar
- name, server/data center, current job + level
- current-expansion Savage progress and Ultimate clears (from FFLogs)
- achievement points / minion / mount counts (from Lodestone)
- a full job level grid (from Lodestone)

Kept deliberately simple (plain shapes + two font weights, no external
design assets besides the job icons in assets/job_icons/) so it's easy to
tweak spacing/colors later without needing image-editing skills - it's all
just numbers in this file.

Everything is drawn at SUPERSAMPLE-times the final size and then shrunk down
with a high-quality resample at the very end. This is what makes the rounded
pill corners, circles and checkmarks look smooth instead of blocky/jagged -
Pillow draws shapes and text with no anti-aliasing of its own, so drawing
"big" and shrinking is the standard trick to fake it.
"""

import io
import os

import requests
from PIL import Image, ImageDraw, ImageFont, ImageOps

from jobs_data import ROLE_COLORS

ASSETS_DIR = os.path.join(os.path.dirname(__file__), "assets")
FONT_BOLD = os.path.join(ASSETS_DIR, "fonts", "WorkSans-Bold.ttf")
FONT_REGULAR = os.path.join(ASSETS_DIR, "fonts", "WorkSans-Regular.ttf")
JOB_ICONS_DIR = os.path.join(ASSETS_DIR, "job_icons")

SUPERSAMPLE = 3  # draw at 3x, then downscale - smooths every edge in the image

CARD_WIDTH = 1200
CARD_HEIGHT = 760
LEFT_PANEL_WIDTH = 380

COLOR_BG = (18, 19, 27)
COLOR_BG_PANEL = (24, 26, 36)
COLOR_TEXT = (240, 240, 245)
COLOR_TEXT_DIM = (170, 172, 185)
COLOR_CLEARED = (124, 77, 210)
COLOR_PARTIAL = (90, 92, 105)
COLOR_NOT_CLEARED = (55, 57, 68)
COLOR_PILL_BG = (36, 38, 50)

HTTP_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; FFXIVUltimateRolesBot/1.0)"}


def _font(path, size):
    return ImageFont.truetype(path, size)


def _fetch_image(url, timeout=10):
    """Downloads an image from a URL and returns a PIL Image, or None on any
    failure (missing avatar, Lodestone hiccup, etc.) - callers draw a plain
    placeholder box instead of crashing the whole card."""
    if not url:
        return None
    try:
        resp = requests.get(url, headers=HTTP_HEADERS, timeout=timeout)
        resp.raise_for_status()
        return Image.open(io.BytesIO(resp.content)).convert("RGBA")
    except Exception:
        return None


def _circle_mask(size):
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, size, size), fill=255)
    return mask


def _paste_circular(base, img, box):
    """Pastes img into base, cropped/resized to a circle filling box=(x, y, size)."""
    x, y, size = box
    if img is None:
        d = ImageDraw.Draw(base)
        d.ellipse((x, y, x + size, y + size), fill=COLOR_PILL_BG, outline=COLOR_TEXT_DIM, width=max(2, size // 40))
        return
    fitted = ImageOps.fit(img, (size, size), method=Image.LANCZOS)
    mask = _circle_mask(size)
    base.paste(fitted, (x, y), mask)


def _draw_check(draw, cx, cy, r, color):
    draw.line(
        [(cx - r * 0.5, cy), (cx - r * 0.15, cy + r * 0.4), (cx + r * 0.55, cy - r * 0.45)],
        fill=color, width=max(2, round(r / 4)), joint="curve",
    )


def _draw_progress_ring(draw, cx, cy, r, fraction, fg_color, bg_color):
    """Draws a circular 'pie' progress indicator (like a tiny donut chart)
    showing fraction (0-1) filled, e.g. for a Savage tier with 2 of 4 fights
    cleared. Starts at 12 o'clock and goes clockwise."""
    bbox = (cx - r, cy - r, cx + r, cy + r)
    draw.ellipse(bbox, fill=bg_color)
    if fraction > 0:
        end_angle = -90 + 360 * fraction
        draw.pieslice(bbox, -90, end_angle, fill=fg_color)


def _draw_cross(draw, cx, cy, r, color):
    w = max(2, round(r / 5))
    draw.line([(cx - r * 0.5, cy - r * 0.5), (cx + r * 0.5, cy + r * 0.5)], fill=color, width=w)
    draw.line([(cx - r * 0.5, cy + r * 0.5), (cx + r * 0.5, cy - r * 0.5)], fill=color, width=w)


def _text_size(draw, text, font):
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0], bbox[3] - bbox[1]


def _pill(draw, box, color, radius):
    draw.rounded_rectangle(box, radius=radius, fill=color)


def render_profile_card(data):
    """data: {
        'name', 'world', 'dc', 'race', 'tribe',
        'portrait_url', 'discord_avatar_url',
        'job_name', 'job_level', 'job_icon_file',
        'savage_tiers': [{'label', 'cleared', 'total'}],
        'ultimates': [{'label', 'cleared'}],
        'achievement_points': int or None,
        'minion_count': int or None,
        'mount_count': int or None,
        'jobs': [{'display', 'icon', 'role', 'level'}],
    }
    Returns a BytesIO containing a PNG.
    """
    SS = SUPERSAMPLE
    W, H = CARD_WIDTH * SS, CARD_HEIGHT * SS
    LP = LEFT_PANEL_WIDTH * SS

    img = Image.new("RGB", (W, H), COLOR_BG)
    draw = ImageDraw.Draw(img)

    f_name = _font(FONT_BOLD, 40 * SS)
    f_server = _font(FONT_REGULAR, 22 * SS)
    f_job = _font(FONT_BOLD, 24 * SS)
    f_section = _font(FONT_BOLD, 18 * SS)
    f_pill = _font(FONT_BOLD, 16 * SS)
    f_count = _font(FONT_BOLD, 26 * SS)
    f_race = _font(FONT_REGULAR, 18 * SS)
    f_level = _font(FONT_BOLD, 13 * SS)

    # ---- Left panel: character render ----
    portrait = _fetch_image(data.get("portrait_url"))
    if portrait:
        fitted = ImageOps.fit(portrait, (LP, H), method=Image.LANCZOS)
        img.paste(fitted, (0, 0))
    else:
        draw.rectangle((0, 0, LP, H), fill=(30, 32, 48))

    bar_h = 46 * SS
    overlay = Image.new("RGBA", (LP, bar_h), (0, 0, 0, 130))
    composited = Image.alpha_composite(img.crop((0, 0, LP, bar_h)).convert("RGBA"), overlay).convert("RGB")
    img.paste(composited, (0, 0))
    draw = ImageDraw.Draw(img)
    pad = 16 * SS
    if data.get("race"):
        draw.text((pad, bar_h // 2), data["race"], font=f_race, fill=COLOR_TEXT, anchor="lm")
    if data.get("tribe"):
        draw.text((LP - pad, bar_h // 2), data["tribe"], font=f_race, fill=COLOR_TEXT, anchor="rm")

    # ---- Right panel ----
    rx = LP + 40 * SS
    draw.rectangle((LP, 0, W, H), fill=COLOR_BG_PANEL)

    avatar_size = 96 * SS
    avatar = _fetch_image(data.get("discord_avatar_url"))
    _paste_circular(img, avatar, (rx, 30 * SS, avatar_size))
    draw = ImageDraw.Draw(img)  # img was touched via composite/paste above

    text_x = rx + avatar_size + 24 * SS
    draw.text((text_x, 30 * SS), data.get("name") or "Unknown", font=f_name, fill=COLOR_TEXT, anchor="la")
    server_line = " / ".join(p for p in [data.get("world"), f"({data['dc']})" if data.get("dc") else None] if p)
    draw.text((text_x, 82 * SS), server_line, font=f_server, fill=COLOR_TEXT_DIM, anchor="la")

    job_icon = None
    job_icon_file = data.get("job_icon_file")
    if job_icon_file:
        path = os.path.join(JOB_ICONS_DIR, f"{job_icon_file}.png")
        if os.path.exists(path):
            job_icon = Image.open(path).convert("RGBA").resize((28 * SS, 28 * SS), Image.LANCZOS)
    job_y = 114 * SS
    job_label = f"Level {data.get('job_level', '?')} {data.get('job_name', '')}".strip()
    if job_icon:
        img.paste(job_icon, (text_x, job_y), job_icon)
        draw = ImageDraw.Draw(img)
        draw.text((text_x + 36 * SS, job_y + 14 * SS), job_label, font=f_job, fill=COLOR_TEXT, anchor="lm")
    else:
        draw.text((text_x, job_y + 14 * SS), job_label, font=f_job, fill=COLOR_TEXT, anchor="lm")

    y = 170 * SS

    def section_header(label, y):
        draw.text((rx, y), label.upper(), font=f_section, fill=COLOR_TEXT_DIM, anchor="la")
        return y + 30 * SS

    pill_h = 36 * SS
    pill_gap = 14 * SS

    # ---- Savage ----
    y = section_header("Savage", y)
    x = rx
    for tier in data.get("savage_tiers", []):
        cleared, total = tier["cleared"], tier["total"]
        full = cleared >= total and total > 0
        label = tier["label"] if full else f"{tier['label']}  {cleared}/{total}"
        w, _ = _text_size(draw, label, f_pill)
        icon_area = 38 * SS
        pill_w = w + icon_area + 16 * SS
        color = COLOR_CLEARED if full else (COLOR_PARTIAL if cleared > 0 else COLOR_NOT_CLEARED)
        _pill(draw, (x, y, x + pill_w, y + pill_h), color, radius=pill_h // 2)
        cy = y + pill_h // 2
        if full:
            _draw_check(draw, x + 20 * SS, cy, 10 * SS, COLOR_TEXT)
        elif cleared > 0:
            _draw_progress_ring(draw, x + 20 * SS, cy, 9 * SS, cleared / total, COLOR_TEXT, COLOR_NOT_CLEARED)
        else:
            _draw_cross(draw, x + 20 * SS, cy, 8 * SS, COLOR_TEXT_DIM)
        draw.text((x + icon_area, cy), label, font=f_pill, fill=COLOR_TEXT, anchor="lm")
        x += pill_w + pill_gap
    y += 56 * SS

    # ---- Ultimates ----
    y = section_header("Ultimates", y)
    x = rx
    for ult in data.get("ultimates", []):
        cleared = ult["cleared"]
        w, _ = _text_size(draw, ult["label"], f_pill)
        icon_area = 34 * SS
        pill_w = max(w + icon_area + 12 * SS, 90 * SS)
        color = COLOR_CLEARED if cleared else COLOR_NOT_CLEARED
        _pill(draw, (x, y, x + pill_w, y + pill_h), color, radius=pill_h // 2)
        cy = y + pill_h // 2
        if cleared:
            _draw_check(draw, x + 20 * SS, cy, 10 * SS, COLOR_TEXT)
        else:
            _draw_cross(draw, x + 20 * SS, cy, 8 * SS, COLOR_TEXT_DIM)
        draw.text((x + icon_area, cy), ult["label"], font=f_pill, fill=COLOR_TEXT, anchor="lm")
        x += pill_w + pill_gap
    y += 60 * SS

    # ---- Achievements / Minions / Mounts ----
    stat_labels = [
        ("Achievements", f"{data['achievement_points']:,} Points" if data.get("achievement_points") is not None else "—"),
        ("Minions", str(data["minion_count"]) if data.get("minion_count") is not None else "—"),
        ("Mounts", str(data["mount_count"]) if data.get("mount_count") is not None else "—"),
    ]
    x = rx
    stat_col_w = (W - rx - 40 * SS) // 3
    stat_pill_h = 34 * SS
    for label, value in stat_labels:
        draw.text((x, y), label.upper(), font=f_section, fill=COLOR_TEXT_DIM, anchor="la")
        w, _ = _text_size(draw, value, f_count)
        pill_w = max(w + 34 * SS, 70 * SS)
        pill_top = y + 28 * SS
        _pill(draw, (x, pill_top, x + pill_w, pill_top + stat_pill_h), COLOR_PILL_BG, radius=stat_pill_h // 2)
        draw.text((x + pill_w // 2, pill_top + stat_pill_h // 2), value, font=f_count, fill=COLOR_TEXT, anchor="mm")
        x += stat_col_w
    y += 90 * SS

    # ---- Job level grid ----
    icon_size = 40 * SS
    cols = 11
    cell_w = (W - rx - 20 * SS) // cols
    x0 = rx
    jobs = data.get("jobs", [])
    for i, job in enumerate(jobs):
        col = i % cols
        row = i // cols
        cx = x0 + col * cell_w
        cy = y + row * 78 * SS
        icon_path = os.path.join(JOB_ICONS_DIR, f"{job['icon']}.png")
        if os.path.exists(icon_path):
            icon_img = Image.open(icon_path).convert("RGBA").resize((icon_size, icon_size), Image.LANCZOS)
            img.paste(icon_img, (cx, cy), icon_img)
            draw = ImageDraw.Draw(img)
        level = job.get("level")
        level_text = str(level) if level else "-"
        badge_color = ROLE_COLORS.get(job.get("role"), COLOR_PILL_BG) if level else COLOR_NOT_CLEARED
        tw, _ = _text_size(draw, level_text, f_level)
        badge_w = max(tw + 16 * SS, 30 * SS)
        badge_h = 18 * SS
        badge_left = cx + icon_size // 2 - badge_w // 2
        badge_top = cy + icon_size + 4 * SS
        _pill(draw, (badge_left, badge_top, badge_left + badge_w, badge_top + badge_h), badge_color, radius=badge_h // 2)
        draw.text((badge_left + badge_w // 2, badge_top + badge_h // 2), level_text, font=f_level, fill=COLOR_TEXT, anchor="mm")

    final = img.resize((CARD_WIDTH, CARD_HEIGHT), Image.LANCZOS)
    buffer = io.BytesIO()
    final.save(buffer, format="PNG")
    buffer.seek(0)
    return buffer
