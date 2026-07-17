#!/usr/bin/env python3
"""快手短视频解析器 - 通过解析页面 Apollo 状态获取无水印视频直链"""

import re, json, time, logging
from typing import Optional, Dict, Any

logger = logging.getLogger("kuaishou")

# 默认快手 Cookie（用户提供）
DEFAULT_COOKIES = {
    "kpf": "PC_WEB",
    "kpn": "KUAISHOU_VISION",
    "clientid": "3",
    "did": "web_3a816da6441fc7ee96a9e3df45f7af37",
}

REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Referer": "https://www.kuaishou.com/",
}

# 快手 URL 正则
SHORT_URL_PATTERN = re.compile(r"https?://v\.kuaishou\.com/([a-zA-Z0-9_\-]+)")
PAGE_URL_PATTERN = re.compile(r"https?://(?:www\.)?kuaishou\.com/short-video/([a-zA-Z0-9_\-]+)")
FULL_URL_PATTERN = re.compile(r"https?://[^/\s]+/(?:fw/photo|short-video)/([a-zA-Z0-9_\-]+)")


def extract_photo_id(text: str) -> Optional[str]:
    """从任意文本中提取快手视频 photoId"""
    if not text:
        return None
    # 直接匹配完整页面 URL
    m = PAGE_URL_PATTERN.search(text)
    if m:
        return m.group(1)
    # 匹配短链接
    m = SHORT_URL_PATTERN.search(text)
    if m:
        return m.group(1)
    # 匹配 chenzhongtech 等 CDN 域名
    m = FULL_URL_PATTERN.search(text)
    if m:
        return m.group(1)
    return None


def resolve_short_url(short_url: str, cookies: dict = None) -> Optional[str]:
    """跟随短链接重定向，获取最终页面 URL"""
    import requests as _req
    try:
        resp = _req.get(
            short_url,
            headers=REQUEST_HEADERS,
            cookies=cookies or DEFAULT_COOKIES,
            timeout=10,
            allow_redirects=True,
        )
        if resp.status_code == 200:
            return resp.url
    except Exception as e:
        logger.warning(f"Short URL resolve failed: {e}")
    return None


def _extract_apollo_state(html: str) -> Optional[dict]:
    """从页面 HTML 中提取 __APOLLO_STATE__ JSON"""
    # 找到 __APOLLO_STATE__= 后的完整 JSON 对象
    marker = "__APOLLO_STATE__="
    idx = html.find(marker)
    if idx < 0:
        return None
    start = idx + len(marker)
    # 找到第一个 {
    brace_start = html.find("{", start)
    if brace_start < 0:
        return None
    depth = 0
    for i in range(brace_start, len(html)):
        c = html[i]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                raw = html[brace_start : i + 1]
                # 还原 Unicode 转义
                raw = raw.replace("\\u002F", "/").replace("\\u0026", "&")
                try:
                    return json.loads(raw)
                except json.JSONDecodeError as e:
                    logger.warning(f"Apollo JSON parse error: {e}")
                    return None
    return None


def parse_photo_id(photo_id: str, cookies: dict = None) -> dict:
    """
    根据 photoId 解析快手视频
    
    Args:
        photo_id: 视频 ID
        cookies: 快手 Cookie 字典
    
    Returns:
        {"success": bool, "data": dict, "error": str}
    """
    result = {"success": False, "data": None, "error": None}
    ck = cookies or DEFAULT_COOKIES
    
    try:
        import requests as _req
        
        # 构建页面 URL
        page_url = f"https://www.kuaishou.com/short-video/{photo_id}"
        logger.info(f"Fetching Kuaishou page: {page_url}")
        
        resp = _req.get(
            page_url,
            headers=REQUEST_HEADERS,
            cookies=ck,
            timeout=15,
        )
        
        if resp.status_code != 200:
            result["error"] = f"页面请求失败 (HTTP {resp.status_code})"
            return result
        
        # 提取 Apollo 状态
        apollo = _extract_apollo_state(resp.text)
        if not apollo:
            result["error"] = "无法解析页面数据（Apollo 状态未找到）"
            return result
        
        dc = apollo.get("defaultClient", {})
        
        # 查找 photo 数据
        photo_key = f"VisionVideoDetailPhoto:{photo_id}"
        photo = dc.get(photo_key)
        
        if not photo:
            # 尝试遍历查找
            for k, v in dc.items():
                if isinstance(v, dict) and v.get("id") == photo_id:
                    photo = v
                    break
        
        if not photo:
            result["error"] = "未找到视频数据"
            return result
        
        # 提取视频信息
        video_url = photo.get("photoUrl", "") or ""
        h265_url = photo.get("photoH265Url", "") or ""
        # 优先使用 H265，否则用普通版
        final_url = h265_url or video_url
        
        if not final_url:
            result["error"] = "未找到视频播放地址"
            return result
        
        # 提取作者信息 - 从 ROOT_QUERY 中找 author 引用
        user_name = ""
        for k, v in dc.items():
            if isinstance(v, dict) and v.get("__typename") == "VisionVideoDetailAuthor":
                user_name = v.get("userName", "") or ""
                if user_name:
                    break
        
        # 计算时长（毫秒转秒）
        duration_ms = photo.get("duration", 0) or 0
        if isinstance(duration_ms, str):
            try:
                duration_ms = int(float(duration_ms))
            except (ValueError, TypeError):
                duration_ms = 0
        
        data = {
            "video_url": final_url,
            "h265_url": h265_url,
            "photo_url": video_url,
            "title": photo.get("caption", "") or "",
            "cover_url": photo.get("coverUrl", "") or "",
            "duration": duration_ms // 1000 if duration_ms else 0,
            "author": user_name,
            "platform": "kuaishou",
            "photo_id": photo_id,
            "like_count": str(photo.get("likeCount", "") or ""),
            "view_count": str(photo.get("viewCount", "") or ""),
            "content_type": "video",
        }
        
        result["success"] = True
        result["data"] = data
        
    except Exception as e:
        logger.error(f"Kuaishou parse failed: {e}")
        result["error"] = f"解析异常: {str(e)[:80]}"
    
    return result


def parse_url(text: str, cookies: dict = None) -> dict:
    """
    从快手分享链接或页面 URL 解析视频（完整入口）
    支持带中文/emojif/换行的混合文本
    
    Args:
        text: 快手分享链接或含链接的文本
        cookies: 快手 Cookie 字典
    
    Returns:
        {"success": bool, "data": dict, "error": str}
    """
    # 从文本中提取纯净的 URL
    clean_url = None
    m = SHORT_URL_PATTERN.search(text)
    if m:
        clean_url = m.group(0)
    if not clean_url:
        m = PAGE_URL_PATTERN.search(text)
        if m:
            clean_url = m.group(0)
    if not clean_url:
        m = FULL_URL_PATTERN.search(text)
        if m:
            clean_url = m.group(0)
    
    if not clean_url:
        return {"success": False, "data": None, "error": "无法识别快手视频链接"}
    
    # 短链接：先解析重定向获取真实 photoId
    if SHORT_URL_PATTERN.search(clean_url):
        resolved = resolve_short_url(clean_url, cookies)
        if resolved:
            photo_id = extract_photo_id(resolved)
            if photo_id:
                return parse_photo_id(photo_id, cookies)
        return {"success": False, "data": None, "error": "快手短链接解析失败，请检查链接是否有效"}
    
    # 直接 URL：提取 photoId
    photo_id = extract_photo_id(clean_url)
    if not photo_id:
        return {"success": False, "data": None, "error": "无法识别快手视频链接"}
    
    return parse_photo_id(photo_id, cookies)
    
    return parse_photo_id(photo_id, cookies)
