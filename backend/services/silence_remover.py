"""
ClipForge — Silence Removal
Auto-cut dead air, long pauses, and filler words from clips.
Uses FFmpeg silencedetect + transcript-based filler word removal.
"""
from __future__ import annotations

import logging
import os
import subprocess
from typing import List, Dict

log = logging.getLogger("clipforge.silence_remover")

FILLER_WORDS = [
    "um", "uh", "like", "you know", "basically",
    "literally", "right", "okay so", "kind of", "sort of",
    "i mean", "actually", "well", "so yeah", "you see",
]


def detect_silence_regions(
    audio_path: str,
    silence_threshold_db: float = -35.0,
    min_silence_duration: float = 0.4,
) -> List[Dict]:
    """
    Use FFmpeg silencedetect filter to find silent regions.
    Returns list of {start, end, duration}.
    """
    cmd = [
        "ffmpeg", "-y",
        "-i", audio_path,
        "-af", f"silencedetect=noise={silence_threshold_db}dB:d={min_silence_duration}",
        "-f", "null", "-",
    ]

    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    stderr = proc.stderr

    regions = []
    silence_start = None

    for line in stderr.split("\n"):
        line = line.strip()
        if "silence_start:" in line:
            try:
                silence_start = float(line.split("silence_start:")[-1].strip())
            except (ValueError, IndexError):
                pass
        elif "silence_end:" in line and silence_start is not None:
            try:
                parts = line.split("silence_end:")
                end_part = parts[1].strip()
                end_str = end_part.split("|")[0].strip()
                silence_end = float(end_str)

                # Also extract duration from the same line
                dur_str = ""
                if "silence_duration:" in end_part:
                    dur_str = end_part.split("silence_duration:")[-1].strip()
                duration = float(dur_str) if dur_str else (silence_end - silence_start)

                regions.append({
                    "start": round(silence_start, 3),
                    "end": round(silence_end, 3),
                    "duration": round(duration, 3),
                })
                silence_start = None
            except (ValueError, IndexError):
                pass

    log.info("Detected %d silence regions in %s", len(regions), os.path.basename(audio_path))
    return regions


def compute_keep_segments(
    total_duration: float,
    silence_regions: List[Dict],
    min_gap_merge: float = 0.3,
    padding: float = 0.05,
) -> List[Dict]:
    """
    Invert silence regions to get speech segments.
    Merge segments that are < min_gap_merge apart.
    Add padding on each side for natural transitions.
    Returns list of {start, end} to keep.
    """
    if not silence_regions:
        return [{"start": 0.0, "end": total_duration}]

    # Build speech segments (gaps between silence)
    speech = []
    prev_end = 0.0

    for silence in silence_regions:
        seg_start = prev_end
        seg_end = silence["start"]
        if seg_end - seg_start > 0.05:  # skip micro-segments
            speech.append({"start": seg_start, "end": seg_end})
        prev_end = silence["end"]

    # Last segment (after last silence)
    if total_duration - prev_end > 0.05:
        speech.append({"start": prev_end, "end": total_duration})

    # Merge close segments
    merged = []
    for seg in speech:
        if merged and seg["start"] - merged[-1]["end"] < min_gap_merge:
            merged[-1]["end"] = seg["end"]
        else:
            merged.append({"start": seg["start"], "end": seg["end"]})

    # Add padding
    for seg in merged:
        seg["start"] = max(0.0, seg["start"] - padding)
        seg["end"] = min(total_duration, seg["end"] + padding)

    log.info("Computed %d keep segments (total: %.1fs of %.1fs)",
             len(merged),
             sum(s["end"] - s["start"] for s in merged),
             total_duration)
    return merged


def remove_silence(
    input_path: str,
    output_path: str,
    threshold_db: float = -35.0,
) -> str:
    """
    Remove silence from video using FFmpeg concat.
    1. Detect silence regions
    2. Compute keep segments
    3. Extract and concat segments
    """
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    work_dir = os.path.dirname(output_path) or "/tmp"

    # Get total duration
    from backend.services.ffmpeg_service import probe_duration
    total_duration = probe_duration(input_path)
    if total_duration <= 0:
        return input_path

    # Detect silence
    regions = detect_silence_regions(input_path, threshold_db)
    keep_segments = compute_keep_segments(total_duration, regions)

    if len(keep_segments) == 1 and keep_segments[0]["start"] == 0.0 and keep_segments[0]["end"] >= total_duration - 0.1:
        # No meaningful silence to remove
        log.info("No significant silence found — skipping removal")
        return input_path

    # Extract segments and build concat list
    concat_path = os.path.join(work_dir, "concat_list.txt")
    with open(concat_path, "w") as f:
        for i, seg in enumerate(keep_segments):
            seg_path = os.path.join(work_dir, f"seg_{i:03d}.mp4")
            cmd = [
                "ffmpeg", "-y",
                "-ss", str(seg["start"]),
                "-to", str(seg["end"]),
                "-i", input_path,
                "-c", "copy",
                seg_path,
            ]
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            if proc.returncode == 0 and os.path.exists(seg_path):
                f.write(f"file '{seg_path}'\n")

    # Concat all segments
    cmd = [
        "ffmpeg", "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", concat_path,
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "23",
        "-c:a", "aac",
        "-b:a", "128k",
        output_path,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)

    # Cleanup
    for i in range(len(keep_segments)):
        seg_path = os.path.join(work_dir, f"seg_{i:03d}.mp4")
        if os.path.exists(seg_path):
            os.remove(seg_path)
    if os.path.exists(concat_path):
        os.remove(concat_path)

    if proc.returncode != 0:
        log.error("Silence removal concat failed: %s", proc.stderr[:300])
        return input_path  # fallback: return original

    log.info("Silence removed: %s → %s", input_path, output_path)
    return output_path


def remove_filler_words(
    input_path: str,
    transcript_words: List[Dict],
    output_path: str,
    filler_words: List[str] = None,
) -> str:
    """
    Scan transcript word timestamps for filler words.
    Build silence_override regions and concatenate with audio silence detection.
    """
    if filler_words is None:
        filler_words = FILLER_WORDS

    filler_regions = []
    words_lower = {w.lower(): w for w in filler_words}

    for i, word in enumerate(transcript_words):
        word_text = word.get("word", "").lower().strip(".,!?;:")
        if word_text in words_lower:
            filler_regions.append({
                "start": word.get("start", 0.0),
                "end": word.get("end", 0.0),
                "word": word.get("word", ""),
            })

    if not filler_regions:
        log.info("No filler words found in transcript")
        return input_path

    log.info("Found %d filler word occurrences — treating as silence", len(filler_regions))

    # Treat filler word regions as additional silence
    all_regions = filler_regions.copy()

    # Also detect audio silence
    try:
        audio_silence = detect_silence_regions(input_path)
        all_regions.extend(audio_silence)
    except Exception:
        pass

    # Sort by start time
    all_regions.sort(key=lambda r: r["start"])

    # Merge overlapping regions
    merged = []
    for region in all_regions:
        if merged and region["start"] < merged[-1]["end"]:
            merged[-1]["end"] = max(merged[-1]["end"], region["end"])
        else:
            merged.append({"start": region["start"], "end": region["end"], "duration": region["end"] - region["start"]})

    from backend.services.ffmpeg_service import probe_duration
    total_duration = probe_duration(input_path)
    keep_segments = compute_keep_segments(total_duration, merged)

    # Rebuild with concat (same as remove_silence)
    work_dir = os.path.dirname(output_path) or "/tmp"
    concat_path = os.path.join(work_dir, "concat_filler.txt")
    with open(concat_path, "w") as f:
        for i, seg in enumerate(keep_segments):
            seg_path = os.path.join(work_dir, f"filler_seg_{i:03d}.mp4")
            cmd = [
                "ffmpeg", "-y",
                "-ss", str(seg["start"]),
                "-to", str(seg["end"]),
                "-i", input_path,
                "-c", "copy",
                seg_path,
            ]
            subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            if os.path.exists(seg_path):
                f.write(f"file '{seg_path}'\n")

    cmd = [
        "ffmpeg", "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", concat_path,
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "23",
        "-c:a", "aac",
        "-b:a", "128k",
        output_path,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)

    # Cleanup
    for i in range(len(keep_segments)):
        seg_path = os.path.join(work_dir, f"filler_seg_{i:03d}.mp4")
        if os.path.exists(seg_path):
            os.remove(seg_path)
    if os.path.exists(concat_path):
        os.remove(concat_path)

    return output_path


def shift_captions(captions: List[Dict], keep_segments: List[Dict]) -> List[Dict]:
    """
    Map original caption timestamps to new timestamps in the silence-removed video.
    """
    if not keep_segments or not captions:
        return captions

    total_offset = 0.0
    new_captions = []

    for cap in captions:
        orig_start = cap.get("start", 0.0)
        orig_end = cap.get("end", 0.0)

        # Find which keep segment this caption belongs to
        new_start = None
        new_end = None

        for seg in keep_segments:
            if seg["start"] <= orig_start <= seg["end"]:
                new_start = total_offset + (orig_start - seg["start"])
            if seg["start"] <= orig_end <= seg["end"]:
                new_end = total_offset + (orig_end - seg["start"])

        if new_start is not None and new_end is not None:
            new_captions.append({**cap, "start": round(new_start, 3), "end": round(new_end, 3)})

        total_offset += seg["end"] - seg["start"]

    log.info("Shifted %d/%d captions for silence-removed video (%d kept)",
             len(new_captions), len(captions), len(keep_segments))
    return new_captions
