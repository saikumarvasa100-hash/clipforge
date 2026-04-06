"""
ClipForge — AI Face/Speaker Tracking Reframe for 9:16 crop.
Uses OpenCV to detect faces, computes smooth crop trajectory,
generates face-tracked 1080x1920 output.
"""
from __future__ import annotations

import logging
import os
import subprocess
from typing import List, Dict

log = logging.getLogger("clipforge.face_tracker")


def detect_faces_per_second(video_path: str) -> List[Dict]:
    """
    Sample 1 frame/sec, detect all face bounding boxes.
    Returns list of {timestamp_sec, faces: [{x, y, w, h, area}]}.
    Picks largest face (closest to camera = active speaker).
    """
    import cv2
    import json
    import tempfile

    cascade = cv2.CascadeClassifier(
        cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
    )
    if cascade.empty():
        log.warning("Haar cascade not loaded — falling back to static crop")
        return []

    # Get video FPS and duration
    cap = cv2.VideoCapture(video_path)
    fps = cap.get(cv2.CAP_PROP_FPS)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    duration = total_frames / fps if fps > 0 else 0
    cap.release()

    # Sample interval in frames
    sample_interval = int(fps) if fps > 0 else 30
    if sample_interval < 1:
        sample_interval = 1

    results = []
    cap = cv2.VideoCapture(video_path)
    frame_idx = 0

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        if frame_idx % sample_interval == 0:
            timestamp = frame_idx / fps if fps > 0 else 0.0

            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            faces = cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5)

            face_list = []
            for (x, y, w, h) in faces:
                area = w * h
                face_list.append({"x": int(x), "y": int(y), "w": int(w), "h": int(h), "area": area})

            # Sort by area — largest face = active speaker
            face_list.sort(key=lambda f: f["area"], reverse=True)

            results.append({
                "timestamp_sec": round(timestamp, 2),
                "faces": face_list,
            })

        frame_idx += 1

    cap.release()
    log.info("Face detection: %d detections across %.1fs of video", len(results), duration)
    return results


def compute_crop_trajectory(
    face_detections: list,
    video_w: int,
    video_h: int,
    target_crop_w: int = 608,
) -> list:
    """
    For each second: compute ideal crop_x = face_center_x - 304,
    clamp to [0, video_w - target_crop_w].
    Apply temporal smoothing: crop_x[t] = 0.85 * crop_x[t-1] + 0.15 * new_x
    Returns list of {time_sec, crop_x, crop_y}.
    """
    if not face_detections:
        return []

    crop_w = target_crop_w
    max_crop_x = video_w - crop_w

    trajectory = []
    prev_crop_x = max(0, (video_w - crop_w) / 2)  # start at center

    for det in face_detections:
        if det["faces"]:
            face = det["faces"][0]  # largest face
            face_center_x = face["x"] + face["w"] // 2
            new_crop_x = face_center_x - crop_w // 2
            # Clamp
            new_crop_x = max(0, min(new_crop_x, max_crop_x))
            # Temporal smoothing
            smoothed_x = 0.85 * prev_crop_x + 0.15 * new_crop_x
            prev_crop_x = smoothed_x
        else:
            # No face detected — use previous trajectory
            smoothed_x = prev_crop_x

        trajectory.append({
            "time_sec": det["timestamp_sec"],
            "crop_x": int(smoothed_x),
            "crop_y": max(0, (video_h - 1920) // 2) if video_h > 1920 else 0,
        })

    log.info("Crop trajectory: %d keyframes computed", len(trajectory))
    return trajectory


def generate_face_tracked_video(
    input_path: str,
    crop_trajectory: list,
    output_path: str,
) -> str:
    """
    Build FFmpeg command with sendcmd filter for dynamic face-tracked crop.
    Uses crop filter keyframes from trajectory.
    """
    if not crop_trajectory:
        from backend.services.ffmpeg_service import reformat_to_9_16
        return reformat_to_9_16(input_path, output_path)

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

    # Build sendcmd file
    cmd_path = os.path.join(os.path.dirname(output_path), "crop_sendcmd.txt")
    with open(cmd_path, "w") as f:
        for keyframe in crop_trajectory:
            t = keyframe["time_sec"]
            cx = keyframe["crop_x"]
            f.write(f"{t} [crop] crop 608 1080 {cx} 0;\n")

    # Build FFmpeg command
    cmd = [
        "ffmpeg", "-y",
        "-i", input_path,
        "-vf", f"sendcmd=f={cmd_path},crop=608:1080:0:0:0,scale=1080:1920:flags=lanczos",
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "23",
        "-c:a", "aac",
        "-b:a", "128k",
        output_path,
    ]

    log.info("Running face-tracked video: %d keyframes", len(crop_trajectory))
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)

    # Cleanup sendcmd file
    if os.path.exists(cmd_path):
        os.remove(cmd_path)

    if proc.returncode != 0:
        log.error("Face-tracked crop failed: %s", proc.stderr[:500])
        # Fallback to static crop
        from backend.services.ffmpeg_service import reformat_to_9_16
        return reformat_to_9_16(input_path, output_path)

    log.info("Face-tracked crop complete: %s", output_path)
    return output_path


def compute_motion_crop(input_path: str, video_w: int, video_h: int) -> list:
    """
    Fallback: detect highest motion region using optical flow.
    Center crop on highest motion region instead.
    """
    import cv2

    cap = cv2.VideoCapture(input_path)
    ret, prev_frame = cap.read()
    if not ret:
        cap.release()
        return []

    prev_gray = cv2.cvtColor(prev_frame, cv2.COLOR_BGR2GRAY)
    fps = cap.get(cv2.CAP_PROP_FPS)

    trajectory = []
    frame_idx = 0
    sample_interval = int(fps) if fps > 1 else 30

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        if frame_idx % sample_interval == 0:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            flow = cv2.calcOpticalFlowFarneback(prev_gray, gray, None, 0.5, 3, 15, 3, 5, 1.2, 0)
            mag, _ = cv2.cartToPolar(flow[..., 0], flow[..., 1])

            # Find region with highest average motion
            h, w = mag.shape
            grid_size = 16
            best_mx, best_my = w // 2, h // 2
            max_motion = 0

            for gy in range(0, h, grid_size):
                for gx in range(0, w, grid_size):
                    region = mag[gy:min(gy + grid_size, h), gx:min(gx + grid_size, w)]
                    avg = region.mean()
                    if avg > max_motion:
                        max_motion = avg
                        best_mx, best_my = gx + grid_size // 2, gy + grid_size // 2

            timestamp = frame_idx / fps if fps > 0 else 0.0
            crop_x = max(0, min(best_mx - 304, video_w - 608))
            trajectory.append({
                "time_sec": round(timestamp, 2),
                "crop_x": crop_x,
                "crop_y": max(0, best_my - 960) if video_h > 1920 else 0,
            })

            prev_gray = gray

        frame_idx += 1

    cap.release()

    # Smooth the motion trajectory
    for i in range(1, len(trajectory)):
        trajectory[i]["crop_x"] = int(0.85 * trajectory[i - 1]["crop_x"] + 0.15 * trajectory[i]["crop_x"])

    log.info("Motion-based crop: %d keyframes", len(trajectory))
    return trajectory
