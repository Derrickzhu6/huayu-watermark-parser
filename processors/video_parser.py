"""
General video parser (non-Douyin platforms)
For Kuaishou, Xiaohongshu, Bilibili etc.
Based on yt-dlp.
"""

import os
import re
import time
import asyncio
import logging

import yt_dlp

logger = logging.getLogger("video_parser")

YDL_OPTS = {
    "skip_download": True,
    "noplaylist": True,
    "max_downloads": 1,
    "socket_timeout": 10,
    "nocheckcertificate": True,
    "extract_flat": False,
    "verbose": False,
    "format_sort": ["res:1080", "res:720", "codec:av01", "codec:vp9", "codec:h264"],
    "format": "bv*+ba/best",
    "user_agent": (
        "Mozilla/5.0 (Linux; Android 13; Pixel 7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.6099.230 Mobile Safari/537.36"
    ),
}


def extract_video_info(url: str) -> dict:
    """Extract video info using yt-dlp"""
    result = {"success": False, "data": None, "error": None}
    try:
        with yt_dlp.YoutubeDL(YDL_OPTS) as ydl:
            info = ydl.extract_info(url, download=False)
            if info is None:
                result["error"] = "Parse returned empty"
                return result
            if info.get("_type") == "playlist":
                entries = info.get("entries", [])
                if not entries:
                    result["error"] = "No videos in playlist"
                    return result
                info = entries[0]
                if info is None:
                    result["error"] = "Empty entry"
                    return result

            video_url = None
            formats = info.get("formats", [])
            if formats:
                for fmt in formats:
                    u = fmt.get("url", "")
                    p = fmt.get("protocol", "")
                    v = fmt.get("vcodec", "none")
                    if u and p not in ("m3u8_native", "m3u8") and v != "none":
                        video_url = u
                        break
            if not video_url:
                video_url = info.get("url") or info.get("webpage_url")
            if not video_url:
                result["error"] = "No video URL found"
                return result

            title = info.get("title", "Untitled")
            title = re.sub(r"[^\w\s\-_\u4e00-\u9fff]", "", title).strip()[:200]
            cover = info.get("thumbnail") or (
                info.get("thumbnails", [{}])[0].get("url", "") if info.get("thumbnails") else ""
            )

            extractor = info.get("extractor", "")
            platform_map = {"Kuaishou": "kuaishou", "Xiaohongshu": "xiaohongshu", "Bilibili": "bilibili"}
            platform = "unknown"
            for k, v in platform_map.items():
                if k.lower() in extractor.lower():
                    platform = v
                    break

            result["success"] = True
            result["data"] = {
                "title": title,
                "video_url": video_url,
                "cover_url": cover,
                "duration": float(info.get("duration", 0) or 0),
                "platform": platform,
                "author": info.get("uploader") or info.get("channel") or "",
            }
    except yt_dlp.utils.DownloadError as e:
        result["error"] = f"Parse failed: {str(e)[:150]}"
    except Exception as e:
        result["error"] = f"Error: {str(e)[:200]}"
    return result


async def extract_video_info_async(url: str, timeout: int = 15) -> dict:
    """Async version"""
    loop = asyncio.get_event_loop()
    try:
        return await asyncio.wait_for(
            loop.run_in_executor(None, extract_video_info, url),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        return {"success": False, "data": None, "error": f"Timeout ({timeout}s)"}
