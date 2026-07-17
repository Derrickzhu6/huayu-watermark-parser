
import os
import cv2
import numpy as np
from PIL import Image
from pathlib import Path
import subprocess

# Auto-detect ffmpeg/ffprobe path
_FFMPEG_PATHS = [
    r"C:\Users\Administrator\AppData\Local\Microsoft\WinGet\Links",
    r"C:\Program Files\FFmpeg\bin",
]
for _p in _FFMPEG_PATHS:
    if os.path.exists(os.path.join(_p, "ffmpeg.exe")):
        os.environ["PATH"] = _p + os.pathsep + os.environ.get("PATH", "")
        break


# Supported formats
IMAGE_READ_FORMATS = {"png", "jpg", "jpeg", "webp", "bmp", "tiff", "tif"}
IMAGE_WRITE_FORMATS = {"png", "jpg", "jpeg", "webp", "bmp", "tiff"}
VIDEO_FORMATS = {"mp4", "avi", "mov", "mkv", "webm", "wmv"}



def find_exe(name):
    """Find ffmpeg/ffprobe path"""
    import shutil
    exe = shutil.which(name)
    if exe:
        return exe
    # Fallback to known paths
    paths = [
        r"C:\Users\Administrator\AppData\Local\Microsoft\WinGet\Links",
        r"C:\Program Files\FFmpeg\bin",
    ]
    for p in paths:
        full = os.path.join(p, name + ".exe")
        if os.path.exists(full):
            return full
    return name


def convert_image(input_path: str, output_path: str, quality: int = 95):
    """Convert image between formats with quality control"""
    ext = os.path.splitext(output_path)[1].lower().lstrip(".")

    # Use PIL for maximum compatibility
    img = Image.open(input_path)

    save_kwargs = {}
    if ext in ("jpg", "jpeg"):
        save_kwargs["quality"] = quality
        if img.mode == "RGBA":
            img = img.convert("RGB")
    elif ext == "webp":
        save_kwargs["quality"] = quality
    elif ext == "png":
        save_kwargs["compress_level"] = 3  # 0-9, lower = faster

    img.save(output_path, **save_kwargs)
    return output_path


def convert_video(input_path: str, output_path: str,
                  codec: str = None, quality: int = 23):
    """Convert video format using FFmpeg"""
    import subprocess

    ext = os.path.splitext(output_path)[1].lower().lstrip(".")

    # Map output format to codec
    codec_map = {
        "mp4": "libx264",
        "avi": "libx264",
        "mov": "libx264",
        "mkv": "libx265",
        "webm": "libvpx",
        "wmv": "wmv2",
    }

    vcodec = codec or codec_map.get(ext, "libx264")

    cmd = [
        find_exe("ffmpeg"), "-y",
        "-i", input_path,
        "-c:v", vcodec,
        "-crf", str(quality),
        "-preset", "medium",
        "-c:a", "aac" if ext in ("mp4", "mov", "mkv") else "copy",
        output_path,
    ]

    result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg error: {result.stderr[:500]}")

    return output_path


def get_video_info(video_path: str) -> dict:
    """Get video metadata using FFprobe"""
    import subprocess
    import json

    cmd = [
        find_exe("ffprobe"), "-v", "quiet",
        "-print_format", "json",
        "-show_format", "-show_streams",
        video_path,
    ]

    result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    if result.returncode != 0:
        raise RuntimeError(f"FFprobe error: {result.stderr[:500]}")

    data = json.loads(result.stdout)
    info = {"format": data.get("format", {}).get("format_name", "unknown")}

    for stream in data.get("streams", []):
        if stream["codec_type"] == "video":
            info["codec"] = stream.get("codec_name")
            info["width"] = stream.get("width")
            info["height"] = stream.get("height")
            info["fps"] = eval(stream.get("r_frame_rate", "0/1"))
            info["duration"] = float(stream.get("duration", 0))
            info["frames"] = int(stream.get("nb_frames", 0))
            break

    info["size_mb"] = round(
        int(data.get("format", {}).get("size", 0)) / 1024 / 1024, 2
    )

    return info
