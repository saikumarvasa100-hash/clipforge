"""
ClipForge — Platform Presets (10+ export profiles).
Defines resolution, FPS, bitrate, max duration/size for each target platform.
"""
from __future__ import annotations

import logging
import os
import subprocess
from dataclasses import dataclass
from typing import Optional

log = logging.getLogger("clipforge.platform_presets")


@dataclass
class PlatformPreset:
    name: str
    width: int
    height: int
    fps: int
    max_duration: int
    max_size_mb: int
    bitrate: str
    fmt: str = "mp4"
    audio_bitrate: str = "128k"


PLATFORM_PRESETS: dict[str, PlatformPreset] = {
    "tiktok": PlatformPreset("TikTok", 1080, 1920, 30, 180, 287, "4M"),
    "instagram_reels": PlatformPreset("Instagram Reels", 1080, 1920, 30, 90, 250, "3.5M"),
    "youtube_shorts": PlatformPreset("YouTube Shorts", 1080, 1920, 60, 60, 256, "8M"),
    "facebook_reels": PlatformPreset("Facebook Reels", 1080, 1920, 30, 90, 1000, "4M"),
    "linkedin_video": PlatformPreset("LinkedIn Video", 1080, 1920, 30, 600, 200, "3M"),
    "twitter_x": PlatformPreset("Twitter/X", 1080, 1920, 30, 140, 512, "5M"),
    "snapchat": PlatformPreset("Snapchat", 1080, 1920, 60, 60, 1000, "4M"),
    "pinterest": PlatformPreset("Pinterest", 1080, 1920, 25, 60, 2000, "2M"),
    "landscape_16_9": PlatformPreset("Landscape 16:9", 1920, 1080, 30, 600, 500, "8M"),
    "square_1_1": PlatformPreset("Square 1:1", 1080, 1080, 30, 60, 250, "4M"),
    "custom": PlatformPreset("Custom", 0, 0, 30, 9999, 9999, "4M"),
}


def encode_for_platform(
    input_path: str,
    platform: str,
    output_path: str,
    custom_config: dict | None = None,
) -> str:
    """
    Encode a video for the target platform's requirements.
    Handles preset lookup, duration trimming, and file size enforcement.
    """
    preset = PLATFORM_PRESETS.get(platform)
    if not preset or platform == "custom":
        if custom_config:
            preset = PlatformPreset(
                platform,
                custom_config.get("w", 1080),
                custom_config.get("h", 1920),
                custom_config.get("fps", 30),
                custom_config.get("max_duration", 9999),
                custom_config.get("max_size_mb", 9999),
                custom_config.get("bitrate", "4M"),
            )
        else:
            preset = PLATFORM_PRESETS["tiktok"]

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

    # Build base FFmpeg command
    cmd = [
        "ffmpeg", "-y",
        "-i", input_path,
        "-vf", f"scale={preset.width}:{preset.height}:force_original_aspect_ratio=decrease,pad={preset.width}:{preset.height}:(ow-iw)/2:(oh-ih)/2:black",
        "-c:v", "libx264",
        "-preset", "fast",
        "-b:v", preset.bitrate,
        "-maxrate", preset.bitrate,
        "-bufsize", f"{int(preset.bitrate.rstrip('M')) * 2}M",
        "-c:a", "aac",
        "-b:a", preset.audio_bitrate,
        "-r", str(preset.fps),
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
    ]

    # Trim if exceeds max duration
    from backend.services.ffmpeg_service import probe_duration
    duration = probe_duration(input_path)
    if duration > preset.max_duration:
        cmd.extend(["-t", str(preset.max_duration)])
        log.info("Trimming %ds clip to %ds for %s", int(duration), preset.max_duration, platform)

    cmd.append(output_path)

    # First pass encode
    log.info("Encoding for %s: %dx%d @ %s fps", platform, preset.width, preset.height, preset.fps)
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)

    if proc.returncode != 0:
        log.error("Encode failed: %s", proc.stderr[:500])
        raise RuntimeError(f"FFmpeg encode failed for {platform}: {proc.stderr[:300]}")

    # Check file size — re-encode with lower bitrate if needed
    file_size_mb = os.path.getsize(output_path) / (1024 * 1024)
    if file_size_mb > preset.max_size_mb:
        log.warning(
            "Output %.1f MB exceeds %s limit (%d MB) — re-encoding at lower bitrate",
            file_size_mb, platform, preset.max_size_mb,
        )
        ratio = preset.max_size_mb / file_size_mb
        new_bitrate = f"{max(1, int(int(preset.bitrate.rstrip('M')) * ratio))}M"
        cmd_b = list(cmd)
        # Replace bitrate values
        for i, arg in enumerate(cmd_b):
            if arg == "-b:v":
                cmd_b[i + 1] = new_bitrate
            elif arg == "-maxrate":
                cmd_b[i + 1] = new_bitrate
        cmd_b[cmd_b.index(output_path)] = output_path + ".retry.mp4"

        proc2 = subprocess.run(cmd_b, capture_output=True, text=True, timeout=600)
        if proc2.returncode == 0 and os.path.exists(output_path + ".retry.mp4"):
            os.replace(output_path + ".retry.mp4", output_path)

    final_size = os.path.getsize(output_path) / (1024 * 1024)
    log.info("Encode complete: %s (%.1f MB)", output_path, final_size)
    return output_path


def validate_for_platform(input_path: str, platform: str) -> dict:
    """Check if a video meets the platform's requirements."""
    preset = PLATFORM_PRESETS.get(platform)
    if not preset:
        return {"valid": False, "error": f"Unknown platform: {platform}"}

    from backend.services.ffmpeg_service import probe_duration
    import subprocess

    # Get dimensions
    ffprobe_cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height",
        "-of", "csv=s=x:p=0",
        input_path,
    ]
    proc = subprocess.run(ffprobe_cmd, capture_output=True, text=True)
    try:
        w, h = proc.stdout.strip().split("x")
        w, h = int(w), int(h)
    except (ValueError, IndexError):
        w, h = 0, 0

    duration = probe_duration(input_path)
    file_size_mb = os.path.getsize(input_path) / (1024 * 1024)

    issues = []
    if w != preset.width or h != preset.height:
        issues.append(f"Resolution: {w}x{h} != {preset.width}x{preset.height}")
    if duration > preset.max_duration:
        issues.append(f"Duration: {duration:.1f}s > {preset.max_duration}s max")
    if file_size_mb > preset.max_size_mb:
        issues.append(f"Size: {file_size_mb:.1f} MB > {preset.max_size_mb} MB max")

    return {
        "valid": len(issues) == 0,
        "platform": platform,
        "preset": {
            "resolution": f"{preset.width}x{preset.height}",
            "fps": preset.fps,
            "max_duration": preset.max_duration,
            "max_size_mb": preset.max_size_mb,
        },
        "actual": {
            "resolution": f"{w}x{h}",
            "duration": round(duration, 1),
            "size_mb": round(file_size_mb, 1),
        },
        "issues": issues,
    }
