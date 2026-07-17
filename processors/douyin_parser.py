"""
抖音短视频深度解析模块
======================
底层基于 yt-dlp，配套 Cookie 轮换 + 多级重试

解析策略（自动轮换）：
  Strategy A: 常规 yt-dlp + Cookie 解析
  Strategy B: 更换 Cookie 池重试
  Strategy C: 模拟移动端 API 抓取（降级方案）

容错：
  - 单次请求超时 8s
  - 总超时 25s
  - 每种策略重试 3 次
  - Cookie 失效自动轮换
"""

import os
import re
import time
import json
import logging
import subprocess
from typing import Optional
from pathlib import Path

import yt_dlp

from .cookies_utils import cookie_pool

logger = logging.getLogger("douyin_parser")

# ─── 常量 ───
REQUEST_TIMEOUT = 8        # 单次请求超时（秒）
TOTAL_TIMEOUT = 25         # 总超时（秒）
MAX_RETRIES = 3            # 每种策略最大重试次数
MAX_REDIRECTS = 8          # 最大 302 跳转层数

# ─── 完整移动端抖音请求头 ───
DOUYIN_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Linux; Android 13; Pixel 7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.6099.230 Mobile Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Referer": "https://www.douyin.com/",
    "Origin": "https://www.douyin.com",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    # 抖音专用
    "X-Device-Info": "platform=android&device_type=Pixel7&os_version=13",
    "X-App-Version": "28.7.0",
    "x-tt-token": "",
    "Cache-Control": "max-age=0",
}

# ─── yt-dlp 基础配置（强制 Cookie + 移动端请求头） ───
def build_ydl_opts(cookie_file: str = None, extra_headers: dict = None) -> dict:
    """构建 yt-dlp 选项，强制 Cookie 和移动端请求头"""
    opts = {
        "skip_download": True,
        "noplaylist": True,
        "max_downloads": 1,
        "socket_timeout": REQUEST_TIMEOUT,
        "nocheckcertificate": True,
        "extract_flat": False,
        "verbose": False,
        "format_sort": ["res:1080", "res:720", "codec:av01", "codec:vp9", "codec:h264"],
        "format": "bv*+ba/best",
        # 注意：不要添加过多自定义请求头，否则会导致 Cookie 认证失效
        # 过多的 headers 会让抖音 API 拒绝带 Cookie 的请求
        "http_headers": {
            "User-Agent": DOUYIN_HEADERS.get("User-Agent", ""),
            "Referer": "https://www.douyin.com/",
        },
    }

    # 强制 Cookie
    if cookie_file and os.path.exists(cookie_file):
        opts["cookiefile"] = cookie_file

    return opts


# ─── 链接预处理 ───
# 抖音短链 / 长链正则
# ===== 全平台链接正则 =====
PLATFORM_PATTERNS = [
    # 抖音
    re.compile(r"https?://v\.douyin\.com/[a-zA-Z0-9_\-]+"),
    re.compile(r"https?://(?:www\.)?douyin\.com/[a-zA-Z0-9_\-/]+"),
    re.compile(r"https?://iesdouyin\.com/[a-zA-Z0-9_\-/]+"),
    # 快手
    re.compile(r"https?://v\.kuaishou\.com/[a-zA-Z0-9_\-]+"),
    re.compile(r"https?://(?:www\.)?kuaishou\.com/[a-zA-Z0-9_\-/]+"),
    # 小红书
    re.compile(r"https?://xhslink\.com/[a-zA-Z0-9_\-]+"),
    re.compile(r"https?://(?:www\.)?xiaohongshu\.com/[a-zA-Z0-9_\-/]+"),
    # B站
    re.compile(r"https?://(?:www\.)?bilibili\.com/[a-zA-Z0-9_\-/]+"),
    re.compile(r"https?://b23\.tv/[a-zA-Z0-9_\-]+"),
    # 通用兜底: http/https URL
    re.compile(r"https?://[^\s\u4e00-\u9fff\uff00-\uffef\u3000-\u303f\"'<>(){}，。；：！？）】］》]+"),
]

# 严格短链正则（纯链接，前缀匹配）
STRICT_SHORT = re.compile(r"https?://(?:v\\.douyin|v\\.kuaishou|xhslink|b23\\.tv)/[a-zA-Z0-9_\\-]+/?")
DOUYIN_URL_PATTERNS = [
    re.compile(r"https?://v\.douyin\.com/[a-zA-Z0-9_\-]+"),       # v.douyin.com/xxx
    re.compile(r"https?://douyin\.com/[a-zA-Z0-9_\-/]+"),         # douyin.com/xxx
    re.compile(r"https?://www\.douyin\.com/[a-zA-Z0-9_\-/]+"),    # www.douyin.com/xxx
    re.compile(r"https?://iesdouyin\.com/[a-zA-Z0-9_\-/]+"),      # iesdouyin.com/xxx
    re.compile(r"https?://[a-z]+\.douyin\.com/[a-zA-Z0-9_\-/]+"), # *.douyin.com
]

# 通用 URL 正则（从任意文本中提取）
GENERIC_URL_PATTERN = re.compile(
    r"https?://[^\s\u4e00-\u9fff\uff00-\uffef\u3000-\u303f"
    r"\u2000-\u206f\ufff0-\uffff\u00a0\u1680\u180e\u2028\u2029"
    r"\u205f\u3000\ufeff]+",
    re.IGNORECASE,
)

# ─── 链接预处理（强制清洗版） ───

# 严格抖音短链正则（只匹配纯净的 v.douyin.com/xxx 格式）
STRICT_DOUYIN_SHORT = re.compile(r"https?://v\.douyin\.com/[a-zA-Z0-9_\-]+/?")

# 无协议前缀的抖音短链（如 v.douyin.com/xxx）
NAKED_DOUYIN_SHORT = re.compile(r"(?<![a-zA-Z])v\.douyin\.com/[a-zA-Z0-9_\-]+/?")

# 宽松抖音域名正则（匹配包含 douyin.com/iesdouyin.com 的任意 URL）
LOOSE_DOUYIN_URL = re.compile(r"https?://[^\s\"'<>(){}，。；：！？）】］》\u4e00-\u9fff\uff00-\uffef]+")

# 非 URL 字符集合（中文、emoji、标点、空格、换行等）
NON_URL_CHARS = re.compile(r"[^\x20-\x7E]+")


def _clean_url_text(raw: str) -> str:
    """
    强制清洗文本：移除所有非 URL 字符（中文、emoji、标点、空格、换行等），
    只保留 ASCII 可打印字符，便于正则精准匹配。
    """
    if not raw:
        return ""
    cleaned = NON_URL_CHARS.sub(" ", raw)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def _auto_complete_url(url: str) -> str:
    """如果链接缺少 https:// 前缀，自动补全"""
    url = url.strip()
    if url.startswith("//"):
        url = "https:" + url
    elif not url.startswith("http://") and not url.startswith("https://"):
        url = "https://" + url
    return url


def extract_douyin_url(text: str) -> Optional[str]:
    """
    从混合文本中提取抖音链接（强制清洗版）。

    流程：
      1. 优先处理纯短链（直接匹配 v.douyin.com/xxx）
      2. 如果失败，强制清洗文本（去掉中文、emoji、空格等非 URL 字符）
      3. 对清洗后的文本用严格正则重新匹配
      4. 仍失败则用宽松正则兜底
      5. 自动补全缺失的 https://
      6. 全部失败才返回 None
    """
    if not text or not text.strip():
        return None

    original = text.strip()

    # ── Pass 0: 纯短链直接匹配（最优先） ──
    m = STRICT_DOUYIN_SHORT.search(original)
    if m:
        url = m.group(0).rstrip("/")
        return _auto_complete_url(url)

    # ── Pass 1: 强制清洗文本 ──
    cleaned = _clean_url_text(original)
    if cleaned:
        m = STRICT_DOUYIN_SHORT.search(cleaned)
        if m:
            url = m.group(0).rstrip("/")
            return _auto_complete_url(url)

        # 无协议前缀的短链（如 v.douyin.com/xxx）
        m = NAKED_DOUYIN_SHORT.search(cleaned)
        if m:
            url = m.group(0).rstrip("/")
            return _auto_complete_url(url)

        m = LOOSE_DOUYIN_URL.search(cleaned)
        if m:
            url = m.group(0).rstrip(".,;:!?/")
            url_lower = url.lower()
            if "douyin.com" in url_lower or "iesdouyin.com" in url_lower:
                return _auto_complete_url(url)

    # ── Pass 2a: 原文本无协议前缀短链 ──
    m = NAKED_DOUYIN_SHORT.search(original)
    if m:
        url = m.group(0).rstrip("/")
        return _auto_complete_url(url)

    # ── Pass 2: 原文本宽松正则兜底 ──
    m = LOOSE_DOUYIN_URL.search(original)
    if m:
        url = m.group(0).rstrip(".,;:!?/")
        url_lower = url.lower()
        if "douyin.com" in url_lower or "iesdouyin.com" in url_lower:
            return _auto_complete_url(url)

    # ── Pass 3: 原有正则最终兜底 ──
    for pattern in DOUYIN_URL_PATTERNS:
        matches = pattern.findall(original)
        for url in matches:
            url = url.rstrip(".,;:!?、，。；：！？)）】］》\"'\\/")
            return _auto_complete_url(url)



def _resolve_short_url(url):
    """跟随短链接重定向，获取真实URL"""
    if not url:
        return url
    try:
        import requests as _req
        hdrs = {
            "User-Agent": "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 Chrome/120.0.6099.230 Mobile Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }
        r = _req.get(url, headers=hdrs, allow_redirects=True, timeout=8)
        if r.status_code == 200 and r.url != url:
            return r.url
        return url
    except Exception:
        return url

def extract_platform_url(text):
    """从混合文本中提取全平台视频链接（抖音/小红书/B站）
    返回: (platform_name, clean_url) 或 (None, None)
    """
    if not text or not text.strip():
        return (None, None)
    original = text.strip()
    douyin_url = extract_douyin_url(original)
    if douyin_url:
        return ("douyin", douyin_url)
    for pattern in PLATFORM_PATTERNS:
        matches = pattern.findall(original)
        for url in matches:
            url = url.rstrip('.,;:!?", \'\\/')
            url = _auto_complete_url(url)
            resolved = _resolve_short_url(url)
            url_lower = resolved.lower()
            if "douyin.com" in url_lower or "iesdouyin.com" in url_lower:
                return ("douyin", resolved)
            elif "xiaohongshu.com" in url_lower or "xhslink" in url_lower:
                return ("xiaohongshu", resolved)
            elif "bilibili.com" in url_lower or "b23.tv" in url_lower:
                return ("bilibili", resolved)
            elif "kuaishou.com" in url_lower:
                return ("kuaishou", url)
            else:
                return ("unknown", url)
    return (None, None)

ERROR_CATEGORIES = {
    "cookie_expired": {
        "keywords": ["Fresh cookies are needed", "Cookie", "cookies", "403", "HTTP Error 403"],
        "message": "Cookie 已失效，请更新 Cookie 文件",
    },
    "link_invalid": {
        "keywords": ["Video unavailable", "404", "not found", "This video is unavailable"],
        "message": "链接无效或视频已被删除",
    },
    "platform_blocked": {
        "keywords": ["429", "Too Many Requests", "rate", "limit", "blocked", "captcha"],
        "message": "平台拦截了请求，请稍后重试",
    },
    "network_timeout": {
        "keywords": ["Timeout", "timed out", "connection", "reset", "refused"],
        "message": "网络超时，请检查网络连接",
    },
    "parse_failed": {
        "keywords": ["Unsupported URL", "not a valid URL", "extractor", "DownloadError"],
        "message": "解析失败，请检查链接是否有效",
    },
}


def classify_error(error_msg: str) -> str:
    """根据错误信息分类，返回中文提示"""
    error_lower = error_msg.lower()
    for category, config in ERROR_CATEGORIES.items():
        for keyword in config["keywords"]:
            if keyword.lower() in error_lower:
                return config["message"]
    return f"解析异常: {error_msg[:100]}"


# ─── 工具函数 ───

def _extract_douyin_video_id(url: str) -> str:
    """从抖音 URL 中提取 video_id（支持多种 URL 格式）"""
    if not url:
        return ""
    # 格式: https://www.douyin.com/video/7662609061070437361
    m = re.search(r"douyin\.com/video/(\d+)", url)
    if m:
        return m.group(1)
    # 格式: https://www.iesdouyin.com/share/video/7662609061070437361
    m = re.search(r"iesdouyin\.com/share/video/(\d+)", url)
    if m:
        return m.group(1)
    # 格式: 纯数字 ID
    m = re.search(r"(\d{17,})", url)
    if m:
        return m.group(1)
    return ""


def _extract_douyin_result(info: dict, url: str, strategy_name: str) -> dict:
    """从 yt-dlp 返回的 info 中提取标准结果"""
    result = {"success": False, "data": None, "error": None}
    
    if info is None:
        result["error"] = "解析返回空结果"
        return result
    
    if info.get("_type") == "playlist":
        entries = info.get("entries", [])
        if entries:
            info = entries[0]
    
    # 获取无水印视频直链
    video_url = ""
    formats = info.get("formats") or []
    
    # 优先级: 无水印 > 高清 > 流畅
    format_prefs = ["nocopyright", "direct", "playback", "hd", "sd", "ld"]
    
    for pref in format_prefs:
        for f in formats:
            fname = (f.get("format_note") or "").lower()
            fext = (f.get("ext") or "").lower()
            fvcodec = (f.get("vcodec") or "").lower()
            if pref in fname:
                video_url = f.get("url") or ""
                break
        if video_url:
            break
    
    if not video_url:
        # 取第一个有 URL 的视频格式
        for f in formats:
            if f.get("url") and f.get("vcodec") != "none":
                video_url = f.get("url", "")
                break
    
    # 兜底：直接用 info 中的网页链接
    if not video_url:
        video_url = info.get("url") or info.get("webpage_url") or ""
    
    content_type = "video"
    if info.get("extractor", "").lower() == "douyin":
        if info.get("title", "").startswith("\u56fe\u6587"):
            content_type = "image_post"
    
    title = info.get("title", "\u672a\u547d\u540d\u89c6\u9891")
    title = re.sub(r"[^\w\s\-_\u2014\u00b7,./()\uff08\uff09\u4e00-\u9fff]", "", title).strip()[:200]
    cover_url = info.get("thumbnail") or (
        info.get("thumbnails", [{}])[0].get("url", "") if info.get("thumbnails") else ""
    )
    duration = info.get("duration", 0) or 0
    uploader = info.get("uploader") or info.get("channel") or info.get("creator") or ""
    
    result["success"] = True
    result["data"] = {
        "title": title,
        "video_url": video_url,
        "cover_url": cover_url,
        "duration": float(duration),
        "platform": "douyin",
        "author": uploader,
        "content_type": content_type,
        "extractor": info.get("extractor", ""),
    }
    logger.info(f"[Strategy {strategy_name}] Success: {title[:30]}...")
    
    return result


# ─── 视频下载函数 ───

def _download_video(video_url: str, strategy_name: str = "") -> str:
    """将视频下载到本地，返回文件名。解决浏览器跨域问题。"""
    import uuid
    from pathlib import Path
    BASE_DIR = Path(__file__).parent.parent
    RESULT_DIR = BASE_DIR / "results"
    RESULT_DIR.mkdir(exist_ok=True)
    
    filename = f"douyin_{uuid.uuid4().hex[:12]}.mp4"
    outpath = RESULT_DIR / filename
    
    try:
        import requests as _req
        resp = _req.get(video_url, timeout=30, stream=True,
                       headers={"User-Agent": "Mozilla/5.0",
                               "Referer": "https://www.douyin.com/"})
        if resp.status_code == 200:
            with open(str(outpath), "wb") as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
            size_kb = outpath.stat().st_size / 1024
            logger.info(f"[{strategy_name}] Downloaded: {filename} ({size_kb:.0f} KB)")
            return filename
    except Exception as e:
        logger.warning(f"[{strategy_name}] Download failed: {e}")
    
    return ""


# ─── 核心解析函数 ───

def parse_with_ytdlp(url: str, cookie_file: str = None, strategy_name: str = "A") -> dict:
    """
    使用 yt-dlp 解析单条视频
    
    Args:
        url: 视频链接
        cookie_file: Cookie 文件路径
        strategy_name: 策略标识（用于日志）
    
    Returns:
        {"success": bool, "data": dict, "error": str}
    """
    result = {"success": False, "data": None, "error": None}

    # 如果传入的是抖音短链，用 requests 手动跟随重定向提取真实 video_id
    # 绕过 yt-dlp 对 iesdouyin.com 重定向 URL 的不兼容问题
    normalized_url = url
    if "douyin.com" in url.lower() and not url.lower().startswith("https://www.douyin.com/video/"):
        import requests as _req
        try:
            _resp = _req.get(url, timeout=8, allow_redirects=True,
                           headers={"User-Agent": DOUYIN_HEADERS.get("User-Agent", ""),
                                   "Accept-Language": "zh-CN,zh;q=0.9"})
            vid = _extract_douyin_video_id(_resp.url)
            if vid:
                normalized_url = f"https://www.douyin.com/video/{vid}"
                logger.info(f"[Strategy {strategy_name}] Followed redirect to video_id={vid}")
        except Exception as _e:
            logger.debug(f"[Strategy {strategy_name}] Redirect follow failed: {_e}")
    
    try:
        opts = build_ydl_opts(cookie_file)
        logger.info(f"[Strategy {strategy_name}] Parsing: {normalized_url[:60]}...")

        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(normalized_url, download=False)

            if info is None:
                result["error"] = "解析返回空结果"
                return result

            # 处理播放列表
            if info.get("_type") == "playlist":
                entries = info.get("entries", [])
                if not entries:
                    result["error"] = "播放列表中无有效视频"
                    return result
                info = entries[0]
                if info is None:
                    result["error"] = "播放列表条目为空"
                    return result

            # 提取视频直链（优先选无水印版本）
            video_url = None
            formats = info.get("formats", [])
            if formats:
                # 先找无水印的格式
                for fmt in formats:
                    url_candidate = fmt.get("url", "")
                    protocol = fmt.get("protocol", "")
                    vcodec = fmt.get("vcodec", "none")
                    note = (fmt.get("format_note") or "").lower()
                    if url_candidate and protocol not in ("m3u8_native", "m3u8") and vcodec != "none":
                        if "watermark" not in note and "watermark" not in url_candidate.lower():
                            video_url = url_candidate
                            break
                # 兜底：如果全部都有水印，取最后一个有水印的
                if not video_url:
                    for fmt in formats:
                        url_candidate = fmt.get("url", "")
                        protocol = fmt.get("protocol", "")
                        vcodec = fmt.get("vcodec", "none")
                        if url_candidate and protocol not in ("m3u8_native", "m3u8") and vcodec != "none":
                            video_url = url_candidate

            if not video_url:
                video_url = info.get("url") or info.get("webpage_url")

            if not video_url:
                result["error"] = "未能提取视频直链"
                return result

            # 判断内容类型（图文/视频）
            content_type = "video"
            if info.get("extractor", "").lower() == "douyin":
                # 抖音图文作品的提取器特征
                if info.get("title", "").startswith("图文"):
                    content_type = "image_post"

            # 提取元数据
            title = info.get("title", "未命名视频")
            title = re.sub(r"[^\w\s\-_—·,./()（）\u4e00-\u9fff]", "", title).strip()[:200]
            cover_url = info.get("thumbnail") or (
                info.get("thumbnails", [{}])[0].get("url", "") if info.get("thumbnails") else ""
            )
            duration = info.get("duration", 0) or 0
            uploader = info.get("uploader") or info.get("channel") or info.get("creator") or ""

            result["success"] = True
            result["data"] = {
                "title": title,
                "video_url": video_url,

                "cover_url": cover_url,
                "duration": float(duration),
                "platform": "douyin",
                "author": uploader,
                "content_type": content_type,
                "extractor": info.get("extractor", ""),
            }
            logger.info(f"[Strategy {strategy_name}] Success: {title[:30]}...")

    except yt_dlp.utils.DownloadError as e:
        error_msg = str(e)
        # 特殊处理：抖音短链被重定向后 yt-dlp 无法识别新 URL 格式
        # 尝试从原始 URL 或重定向 URL 中提取 video_id，用标准格式重试
        if "Unsupported URL" in error_msg:
            # 从错误消息中提取 video_id（重定向后的长链接包含真实 video_id）
            video_id = _extract_douyin_video_id(error_msg)
            if not video_id:
                video_id = _extract_douyin_video_id(url)
            if video_id:
                standard_url = f"https://www.douyin.com/video/{video_id}"
                logger.info(f"[Strategy {strategy_name}] Retrying with standard URL: {standard_url}")
                try:
                    opts = build_ydl_opts(cookie_file)
                    with yt_dlp.YoutubeDL(opts) as ydl:
                        info = ydl.extract_info(standard_url, download=False)
                        if info and info.get("_type") != "playlist":
                            result = _extract_douyin_result(info, standard_url, strategy_name)
                except yt_dlp.utils.DownloadError as e2:
                    # 标准格式触发了 Douyin 提取器，保留其错误信息（如 Fresh cookies needed）
                    error_msg = str(e2)
                    logger.info(f"[Strategy {strategy_name}] Standard URL error: {error_msg[:150]}")
                except Exception:
                    pass
        if not result["success"]:
            result["error"] = classify_error(error_msg)
            logger.warning(f"[Strategy {strategy_name}] DownloadError: {error_msg[:150]}")
    except yt_dlp.utils.ExtractorError as e:
        result["error"] = classify_error(str(e))
        logger.warning(f"[Strategy {strategy_name}] ExtractorError: {str(e)[:150]}")
    except yt_dlp.utils.GeoRestrictedError:
        result["error"] = "该视频受地域限制，当前 IP 无法访问"
    except Exception as e:
        result["error"] = classify_error(str(e))
        logger.error(f"[Strategy {strategy_name}] Unexpected: {str(e)[:200]}")

    return result


def parse_with_retry(url: str) -> dict:
    """
    多策略多级重试解析入口
    
    策略轮换：
      A. 使用当前 Cookie 解析
      B. 切换到 Cookie 池下一组 Cookie
      C. 清除 Cookie，使用移动端 Headers 直连
    
    每种策略最多重试 MAX_RETRIES 次。
    总超时 TOTAL_TIMEOUT 秒。
    """
    start_time = time.time()
    last_error = "所有解析策略均失败"

    # 检查 Cookie 过期
    cookie_pool.check_expiry()

    strategies = [
        {"name": "A", "cookie": True,    "desc": "常规 Cookie 解析"},
        {"name": "B", "cookie": True,    "desc": "切换 Cookie 池"},
        {"name": "C", "cookie": False,   "desc": "模拟移动端 API"},
        {"name": "D", "cookie": False,   "desc": "Playwright 浏览器渲染"},
    ]

    for strategy in strategies:
        for attempt in range(1, MAX_RETRIES + 1):
            # 检查总超时
            elapsed = time.time() - start_time
            if elapsed > TOTAL_TIMEOUT:
                logger.warning(f"Total timeout ({TOTAL_TIMEOUT}s) exceeded")
                return {"success": False, "data": None, "error": "解析超时（超过 25 秒），请稍后重试"}

            cookie_file = None
            if strategy["cookie"]:
                if strategy["name"] == "B":
                    # 策略 B: 轮换到下一组 Cookie
                    cookie_pool.rotate()
                cookie_file = cookie_pool.get_current_cookie_file()

            logger.info(f"Attempt {attempt}/{MAX_RETRIES} [策略{strategy['name']}-{strategy['desc']}]")

            if strategy["name"] == "D":
                try:
                    from processors.douyin_playwright import parse as pw_parse
                    result = pw_parse(url)
                    if result["success"]:
                        return result
                    last_error = result.get("error", "Playwright失败")
                    continue
                except Exception as e:
                    last_error = "Playwright不可用: " + str(e)
                    continue
            else:
                result = parse_with_ytdlp(url, cookie_file, f"{strategy['name']}-{attempt}")

            if result["success"]:
                return result

            last_error = result.get("error", "未知错误")

            # 如果错误是 Cookie 失效，立即标记并切换
            if "Cookie" in (result.get("error") or ""):
                cookie_pool.mark_failed()
                logger.info("Cookie invalid, switching to next group")
                continue

            # 如果是链接无效，直接返回，不继续重试
            if "链接无效" in (result.get("error") or ""):
                return result

            # 等待短暂重试间隔
            time.sleep(0.5)

    return {"success": False, "data": None, "error": last_error}


async def async_parse(url: str) -> dict:
    """
    异步解析入口（供 FastAPI 调用）
    使用 run_in_executor 避免阻塞事件循环
    """
    import asyncio
    loop = asyncio.get_event_loop()
    try:
        result = await asyncio.wait_for(
            loop.run_in_executor(None, parse_with_retry, url),
            timeout=TOTAL_TIMEOUT + 5,  # 额外 5s 缓冲区
        )
        return result
    except asyncio.TimeoutError:
        return {
            "success": False,
            "data": None,
            "error": "解析超时（超过 30 秒），请检查网络或稍后重试",
        }

