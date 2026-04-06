"""
ClipForge — Caption Style System
6 styles: classic, highlighted, dark_box, tiktok_style, minimal, karaoke.
Each style defines font, colors, size, position, and special effects.
"""
from __future__ import annotations

import base64
import logging
import os
import subprocess
from typing import Dict, List

log = logging.getLogger("clipforge.caption_styles")

CAPTION_STYLES = {
    "classic": {
        "font": "Arial-Bold",
        "fontsize": 56,
        "fontcolor": "white",
        "bordercolor": "black",
        "borderw": 3,
        "box": 0,
        "uppercase": False,
        "position": "bottom_center",
        "position_y_ratio": 0.85,
    },
    "highlighted": {
        "font": "Arial-Bold",
        "fontsize": 52,
        "fontcolor": "white",
        "bordercolor": "black",
        "borderw": 2,
        "box": 1,
        "boxcolor": "#FF6B35@0.85",
        "uppercase": False,
        "position": "bottom_center",
        "position_y_ratio": 0.85,
    },
    "dark_box": {
        "font": "Arial-Bold",
        "fontsize": 52,
        "fontcolor": "white",
        "bordercolor": "transparent",
        "borderw": 0,
        "box": 1,
        "boxcolor": "black@0.7",
        "boxborderw": 8,
        "uppercase": False,
        "position": "bottom_center",
        "position_y_ratio": 0.85,
    },
    "tiktok_style": {
        "font": "Arial-Bold",
        "fontsize": 60,
        "fontcolor": "white",
        "bordercolor": "#000000",
        "borderw": 4,
        "box": 0,
        "uppercase": True,
        "position": "center",
        "position_y_ratio": 0.5,
    },
    "minimal": {
        "font": "Arial",
        "fontsize": 44,
        "fontcolor": "white@0.9",
        "bordercolor": "black@0.5",
        "borderw": 1,
        "box": 0,
        "uppercase": False,
        "position": "bottom_center",
        "position_y_ratio": 0.9,
    },
    "karaoke": {
        "font": "Arial-Bold",
        "fontsize": 56,
        "active_word_color": "#FFD700",
        "inactive_word_color": "white",
        "bordercolor": "black",
        "borderw": 3,
        "box": 0,
        "uppercase": False,
        "position": "bottom_center",
        "position_y_ratio": 0.85,
    },
}


def _build_drawtext_filter(
    style: dict,
    text: str,
    enable_expr: str,
    video_h: int = 1920,
    video_w: int = 1080,
) -> str:
    """Build a single drawtext filter for FFmpeg."""
    escaped = text.replace("'", "").replace(":", "\\:").replace(",", "\\,")
    if style.get("uppercase"):
        escaped = escaped.upper()

    pos_y_offset = style.get("position_y_ratio", 0.85)
    y_pos = int(video_h * pos_y_offset)

    parts = [
        f"drawtext=text='{escaped}'",
        f"x=(w-text_w)/2",
        f"y={y_pos}",
        f"fontcolor={style.get('fontcolor', 'white')}",
        f"bordercolor={style.get('bordercolor', 'black')}",
        f"borderw={style.get('borderw', 3)}",
        f"fontsize={style.get('fontsize', 56)}",
        f"box=1" if style.get("box") else "box=0",
        f"enable='{enable_expr}'",
    ]

    if style.get("boxcolor"):
        parts.insert(6, f"boxcolor={style['boxcolor']}")
    if style.get("boxborderw"):
        parts.insert(7, f"boxborderw={style['boxborderw']}")

    return ":".join(parts)


def _build_karaoke_filters(
    style: dict,
    words: List[Dict],
    chunk_idx: int,
    video_h: int = 1920,
    video_w: int = 1080,
) -> List[str]:
    """
    For karaoke style: build a drawtext filter per word,
    highlighting the active word in gold and inactive words in white.
    """
    filters = []
    pos_y_offset = style.get("position_y_ratio", 0.85)
    y_pos = int(video_h * pos_y_offset)

    # Build all text in inactive color, then overlay active word
    all_text = " ".join(
        w.get("word", "") for w in words
    ).replace("'", "").replace(":", "\\:").replace(",", "\\,")

    if style.get("uppercase"):
        all_text = all_text.upper()

    start = words[0].get("start", 0.0) if words else 0.0
    end = words[-1].get("end", 0.0) if words else 0.0

    # Background text (all words in inactive color)
    bg_filter = ":".join([
        f"drawtext=text='{all_text}'",
        f"x=(w-text_w)/2",
        f"y={y_pos}",
        f"fontcolor={style.get('inactive_word_color', 'white')}",
        f"bordercolor={style.get('bordercolor', 'black')}",
        f"borderw={style.get('borderw', 3)}",
        f"fontsize={style.get('fontsize', 56)}",
        f"box=0",
        f"enable='between(t\\,{start}\\,{end})'",
    ])
    filters.append(bg_filter)

    # For each word, overlay in active color at the right time
    x_offsets = []
    current_x = 0
    for w in words:
        word_text = w.get("word", "")
        word_len = len(word_text) + 1  # +1 for space
        char_width = style.get("fontsize", 56) * 0.6
        offset = current_x
        x_offsets.append(offset)
        current_x += word_len * char_width

    for i, w in enumerate(words):
        w_text = w.get("word", "").replace("'", "").replace(":", "\\:")
        if style.get("uppercase"):
            w_text = w_text.upper()
        w_start = w.get("start", 0.0)
        w_end = w.get("end", 0.0)

        # Simple approach: use a separate drawtext for each word's highlight
        # (positioning is approximate — good enough for karaoke effect)
        highlight_filter = ":".join([
            f"drawtext=text='{w_text}'",
            f"x=(w-text_w)/2+iw/{max(len(words),1)}*{i}",
            f"y={y_pos}",
            f"fontcolor={style.get('active_word_color', '#FFD700')}",
            f"bordercolor={style.get('bordercolor', 'black')}",
            f"borderw={style.get('borderw', 3)}",
            f"fontsize={style.get('fontsize', 56)}",
            f"box=0",
            f"enable='between(t\\,{w_start}\\,{w_end})'",
        ])
        filters.append(highlight_filter)

    return filters


def build_caption_filters(
    style_name: str,
    words_json: str,
    video_h: int = 1920,
    video_w: int = 1080,
) -> str:
    """
    Build a complete FFmpeg -vf string for the given caption style.
    """
    import json

    style = CAPTION_STYLES.get(style_name, CAPTION_STYLES["classic"])
    words = json.loads(words_json) if isinstance(words_json, str) else words_json

    if not words:
        return ""

    # Group words into chunks: max 5 words or max 2.5 seconds
    chunks: List[List[Dict]] = []
    current_chunk: List[Dict] = []

    for w in words:
        current_chunk.append(w)
        chunk_duration = current_chunk[-1].get("end", 0) - current_chunk[0].get("start", 0)
        if len(current_chunk) >= 5 or chunk_duration >= 2.5:
            chunks.append(current_chunk)
            current_chunk = []

    if current_chunk:
        chunks.append(current_chunk)

    # Simplified: all non-karaoke styles use word-grouped filters
    # Karaoke handled via word-level overlays in a separate method if needed
    filters = []
    for chunk in chunks:
        text = " ".join(w.get("word", "") for w in chunk)
        if style.get("uppercase"):
            text = text.upper()
        start = chunk[0].get("start", 0.0)
        end = chunk[-1].get("end", 0.0)
        enable = f"between(t\\,{start}\\,{end})"
        filter = _build_drawtext_filter(style, text, enable, video_h, video_w)
        filters.append(filter)
    return ",".join(filters)


def burn_styled_captions(
    input_path: str,
    words_json: str,
    style_name: str,
    output_path: str,
) -> str:
    """
    Burn captions with the given style onto the video.
    """
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

    vf = build_caption_filters(style_name, words_json)

    if not vf:
        return input_path

    cmd = [
        "ffmpeg", "-y",
        "-i", input_path,
        "-vf", vf,
        "-c:a", "copy",
        output_path,
    ]

    log.info("Burning %s captions onto %s", style_name, os.path.basename(output_path))
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)

    if proc.returncode != 0:
        log.error("Caption burning failed (%s): %s", style_name, proc.stderr[:500])
        # Fallback to classic style
        classic_vf = build_caption_filters("classic", words_json)
        if classic_vf:
            cmd_classic = [
                "ffmpeg", "-y",
                "-i", input_path,
                "-vf", classic_vf,
                "-c:a", "copy",
                output_path,
            ]
            proc2 = subprocess.run(cmd_classic, capture_output=True, text=True, timeout=600)
            if proc2.returncode == 0:
                log.info("Fallback to classic captions succeeded")
                return output_path
        raise RuntimeError(f"Caption burning failed for style {style_name}")

    log.info("Caption burning (%s) complete: %s", style_name, output_path)
    return output_path


def get_caption_preview_thumbnail(
    video_path: str,
    style_name: str,
    timestamp: float = 5.0,
) -> str:
    """
    Extract a single frame at the timestamp, overlay a caption preview,
    return as base64 JPEG for frontend preview.
    """
    style = CAPTION_STYLES.get(style_name, CAPTION_STYLES["classic"])
    preview_dir = "/tmp/clipforge/previews"
    os.makedirs(preview_dir, exist_ok=True)

    # Extract frame at timestamp
    frame_path = os.path.join(preview_dir, f"preview_{style_name}.jpg")
    cmd = [
        "ffmpeg", "-y",
        "-ss", str(timestamp),
        "-i", video_path,
        "-vframes", "1",
        "-q:v", "2",
        frame_path,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if proc.returncode != 0:
        return ""

    # Overlay sample caption text to show style
    sample_text = "This is a preview of the style".upper() if style.get("uppercase") else "This is a preview of the style"
    y_pos = int(1920 * style.get("position_y_ratio", 0.85))

    overlay_cmd = [
        "ffmpeg", "-y",
        "-i", frame_path,
        "-vf", ":".join([
            f"drawtext=text='{sample_text}'",
            f"x=(w-text_w)/2",
            f"y={y_pos}",
            f"fontcolor={style.get('fontcolor', 'white')}",
            f"bordercolor={style.get('bordercolor', 'black')}",
            f"borderw={style.get('borderw', 3)}",
            f"fontsize={style.get('fontsize', 56)}",
            f"box=1" if style.get("box") else "box=0",
        ]) + (f",boxcolor={style['boxcolor']}" if style.get("boxcolor") else ""),
        "-q:v", "2",
        frame_path,
    ]
    subprocess.run(overlay_cmd, capture_output=True, text=True, timeout=60)

    # Read as base64
    with open(frame_path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")
