"""
ClipForge -- FFmpeg Service
Real FFmpeg filter chains for video processing.
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
from typing import List, Dict

log = logging.getLogger("clipforge.ffmpeg_service")

FFMPEG = "ffmpeg"
FFPROBE = "ffprobe"


def _run(cmd: List[str], timeout: int = 600) -> subprocess.CompletedProcess:
    """Run FFmpeg command and log stderr."""
    log.info("Executing: %s", " ".join(cmd))
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if proc.returncode != 0:
        log.error("FFmpeg failed: %s", proc.stderr[:1000])
        raise RuntimeError(f"FFmpeg command failed: {proc.stderr[:500]}")
    return proc


def cut_clip(input_path: str, start_time: float, end_time: float, output_path: str) -> str:
    """Extract a segment, re-encode H.264 + AAC."""
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    cmd = [
        FFMPEG, "-y",
        "-ss", str(start_time),
        "-to", str(end_time),
        "-i", input_path,
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "23",
        "-c:a", "aac",
        "-b:a", "128k",
        output_path,
    ]
    _run(cmd)
    return output_path


def reformat_to_9_16(input_path: str, output_path: str) -> str:
    """Rescale + pad any resolution to 1080x1920 (9:16)."""
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    vf = (
        "scale=iw*min(1080/iw\\,1920/ih):ih*min(1080/iw\\,1920/ih),"
        "pad=1080:1920:(1080-iw)/2:(1920-ih)/2:black,setsar=1"
    )
    cmd = [
        FFMPEG, "-y",
        "-i", input_path,
        "-vf", vf,
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "23",
        "-c:a", "aac",
        "-b:a", "128k",
        "-maxrate", "5M",
        "-bufsize", "10M",
        output_path,
    ]
    _run(cmd)
    return output_path


def _build_caption_filter(words: List[Dict], width: int = 1080, height: int = 1920) -> str:
    """Build an FFmpeg drawtext filter chain from Whisper word timestamps."""
    # Group words into caption chunks: max 4 words or max 2 seconds per chunk
    chunks: List[Dict] = []
    current_chunk: List[Dict] = []

    for w in words:
        current_chunk.append(w)
        chunk_duration = current_chunk[-1]["end"] - current_chunk[0]["start"]
        if len(current_chunk) >= 4 or chunk_duration >= 2.0:
            text = " ".join(w["word"] for w in current_chunk)
            chunks.append({
                "start": current_chunk[0]["start"],
                "end": current_chunk[-1]["end"],
                "text": text,
            })
            current_chunk = []

    if current_chunk:
        text = " ".join(w["word"] for w in current_chunk)
        chunks.append({
            "start": current_chunk[0]["start"],
            "end": current_chunk[-1]["end"],
            "text": text,
        })

    if not chunks:
        return ""

    base_opts = (
        f"fontfile='/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'"
        f":fontsize=56:fontcolor=white:bordercolor=black:borderw=3"
        f":box=0:x=(w-text_w)/2:y={height}-200"
    )

    filter_parts = []
    for i, chunk in enumerate(chunks):
        escaped_text = chunk["text"].replace("'", "'").replace(":", "\\:")
        enable = f"between(t\\,{chunk['start']}\\,{chunk['end']})"
        part = f"drawtext=text='{escaped_text}':{base_opts}:enable='{enable}'"
        filter_parts.append(part)

    return ",".join(filter_parts)


def burn_captions(input_path: str, words_json: str, output_path: str) -> str:
    """Burn word-level Whisper captions onto the video."""
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    words = json.loads(words_json)
    caption_filter = _build_caption_filter(words)

    if not caption_filter:
        # no captions to burn, just copy
        _run([FFMPEG, "-y", "-i", input_path, "-c", "copy", output_path])
        return output_path

    cmd = [
        FFMPEG, "-y",
        "-i", input_path,
        "-vf", caption_filter,
        "-c:a", "copy",
        output_path,
    ]
    _run(cmd)
    return output_path


def add_intro_zoom(input_path: str, output_path: str, duration: float = 0.5) -> str:
    """Apply a 1.1x zoom-in on the first {duration} seconds."""
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    fps = 30
    frames = int(duration * fps)
    vf = (
        f"zoompan=z='if(lte(on\\,{frames})\\,1.1\\,1)'"
        f":d={frames}"
        f":x='iw/2-(iw/zoom/2)'"
        f":y='ih/2-(ih/zoom/2)'"
        f":s=1080x1920"
    )
    cmd = [
        FFMPEG, "-y",
        "-i", input_path,
        "-vf", vf,
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "23",
        "-c:a", "aac",
        "-b:a", "128k",
        output_path,
    ]
    _run(cmd)
    return output_path


def probe_duration(input_path: str) -> float:
    """Return the duration of a media file in seconds."""
    cmd = [
        FFPROBE, "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        input_path,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    try:
        return float(proc.stdout.strip())
    except (ValueError, TypeError):
        return 0.0
