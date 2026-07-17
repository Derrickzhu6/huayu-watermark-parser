"""
短视频解析 API —— 基于 yt-dlp 核心引擎
========================================
支持平台：抖音 / 快手 / 小红书 / B站 / 微视 / 西瓜视频 等所有 yt-dlp 支持平台

核心原则：
  1. 所有视频解析 100% 由 yt-dlp 处理，不自行编写平台接口抓取
  2. 只做两件事：从混合文本中提取 URL + 把 URL 交给 yt-dlp
  3. 返回无水印直链、标题、封面、时长
"""

import os
import uuid
import json
import re
import time
import asyncio
import logging
from typing import Optional
from collections import defaultdict
from contextlib import asynccontextmanager
from pathlib import Path

import yt_dlp

# Frontend directory
FRONTEND_DIR = Path(__file__).parent / "frontend"
BASE_DIR = Path(__file__).parent
UPLOAD_DIR = BASE_DIR / "uploads"
RESULT_DIR = BASE_DIR / "results"
UPLOAD_DIR.mkdir(exist_ok=True)
RESULT_DIR.mkdir(exist_ok=True)
from fastapi import FastAPI, HTTPException, Request, UploadFile, File, Form
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

import cv2
import numpy as np
from processors.inpainting import (
    create_mask_from_strokes, refine_inpaint
)
from processors.quality_inpaint import quality_inpaint
from processors.frequency import frequency_filter, text_watermark_removal
from processors.color_filter import remove_by_color, remove_alpha_watermark
from processors.auto_detect import auto_detect_watermark, auto_detect_and_inpaint
from processors.smart_inpaint import smart_inpaint
from processors.process_logger import init_logger, get_logs, log_watermark_operation
from processors.converter import convert_image, convert_video, get_video_info, VIDEO_FORMATS
from processors.douyin_parser import async_parse, extract_douyin_url, cookie_pool

# ─── 日志配置 ───
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("video_parser")

# ═══════════════════════════════════════════════
#  第一部分：URL 提取（唯一的前置处理）
# ═══════════════════════════════════════════════

# 支持的短链域名列表
SHORT_DOMAINS = [
    "v.douyin.com", "douyin.com", "iesdouyin.com",
    "xhslink.com", "xiaohongshu.com", "xhscdn.com",
    "kuaishou.com", "ksyun.com", "kl.ty", "v.kuaishou.com",
    "bilibili.com", "b23.tv", "bili22.cn", "bili33.cn",
    "weixin.qq.com", "tencentvideo",
    "ixigua.com", "huoshan.com", "pinduoduo.com",
]

# 通用 URL 正则：匹配 http/https 开头的链接
# 能跳过中文、emoji、空格、特殊符号等非 URL 字符
URL_PATTERN = re.compile(
    r"https?://[^\s\u4e00-\u9fff\uff00-\uffef\u3000-\u303f"
    r"\u2000-\u206f\ufff0-\uffff\u00a0\u1680\u180e\u2028\u2029"
    r"\u205f\u3000\ufeff\u2100-\u214f\u2190-\u21ff]+",
    re.IGNORECASE,
)


def extract_url(text: str) -> Optional[str]:
    """
    从混合文本中提取视频分享链接。
    
    支持输入：
    - 纯链接：https://v.douyin.com/xxxx
    - 带文案："太美了！https://v.douyin.com/xxxx 快来看"
    - 带 emoji："😍 https://v.douyin.com/xxxx 🎉"
    - 带换行和空格的多行分享文案
    
    策略：
    1. 从文本中匹配所有 http 链接
    2. 过滤出属于已知短视频平台的链接
    3. 返回第一个匹配到的链接（最可能是用户分享的）
    """
    if not text or not text.strip():
        return None

    text = text.strip()
    matches = URL_PATTERN.findall(text)

    if not matches:
        return None

    # 清理 URL 尾部多余的标点符号
    cleaned = []
    for url in matches:
        url = url.rstrip(".,;:!?、，。；：！？)）】］》\"'\"'")
        cleaned.append(url)

    # 优先匹配已知短视频平台域名
    for url in cleaned:
        url_lower = url.lower()
        for domain in SHORT_DOMAINS:
            if domain in url_lower:
                return url

    # 兜底：返回第一个匹配的链接
    return cleaned[0]


# ═══════════════════════════════════════════════
#  第二部分：IP 限流器
# ═══════════════════════════════════════════════

class RateLimiter:
    """
    简单的 IP 限流器 —— 滑动窗口算法。
    默认配置：每 IP 每分钟最多 10 次请求。
    """

    def __init__(self, max_requests: int = 10, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        # { "ip": [timestamp1, timestamp2, ...] }
        self._records: dict[str, list[float]] = defaultdict(list)

    def is_allowed(self, ip: str) -> bool:
        now = time.time()
        cutoff = now - self.window_seconds

        # 清理过期的记录
        self._records[ip] = [t for t in self._records[ip] if t > cutoff]

        if len(self._records[ip]) >= self.max_requests:
            return False

        self._records[ip].append(now)
        return True

    def remaining(self, ip: str) -> int:
        """返回当前 IP 还剩余多少次请求机会"""
        cutoff = time.time() - self.window_seconds
        self._records[ip] = [t for t in self._records[ip] if t > cutoff]
        return max(0, self.max_requests - len(self._records[ip]))

    def reset(self, ip: str):
        """手动重置某个 IP 的记录"""
        self._records[ip] = []


# 全局限流器实例
rate_limiter = RateLimiter()


# ═══════════════════════════════════════════════
#  # yt-dlp 延迟导入函数
_yt_dlp = None
def get_ytdlp():
    global _yt_dlp
    if _yt_dlp is None:
        import yt_dlp
        from yt_dlp.utils import DownloadError
        _yt_dlp = yt_dlp
        _yt_dlp.DownloadError = DownloadError
    return _yt_dlp
# 第三部分：yt-dlp 核心解析器
# ═══════════════════════════════════════════════

# yt-dlp 全局选项
YDL_OPTS = {
    # 不下载任何文件，只提取信息
    "skip_download": True,
    # 不播放列表，只处理单个视频
    "noplaylist": True,
    # 限制最多处理 1 个视频（防批量）
    "max_downloads": 1,
    # 网络超时（秒）
    "socket_timeout": 10,
    # 提取器的详细日志（调试用）
    "verbose": False,
    # 移动端 User-Agent 防止反爬
    "user_agent": (
        "Mozilla/5.0 (Linux; Android 13; Pixel 7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.6099.230 Mobile Safari/537.36"
    ),
    # 提取嵌入的元数据
    "extract_flat": False,
    # 获取所有格式信息
    "listsubtitles": False,
    # 不检查证书
    "nocheckcertificate": True,
}

# 获取无水印格式的配置
# yt-dlp 对抖音等平台会自动选择无水印的格式，
# 这里显式指定格式选择规则确保最优质量
FORMAT_SORT_OPTS = {
    "format_sort": [
        "res:1080",    # 优先 1080p
        "res:720",     # 其次 720p
        "codec:av01",  # 优先 AV1 编码
        "codec:vp9",   # 其次 VP9
        "codec:h264",  # 最后 H.264
        "size",        # 文件大小（小优先）
        "br",          # 码率（高优先）
        "proto",       # 协议（https > m3u8 > dash）
    ],
    "format": "bv*+ba/best",  # 最佳视频 + 最佳音频
}


def extract_video_info(url: str) -> dict:
    """
    核心解析函数 —— 使用 yt-dlp 提取视频信息。
    
    Args:
        url: 短视频分享链接（已从混合文本中提取）
    
    Returns:
        {
            "success": bool,
            "data": {
                "title": str,          # 视频标题
                "video_url": str,      # 无水印视频直链
                "cover_url": str,      # 封面图地址
                "duration": float,     # 视频时长（秒）
                "platform": str,       # 平台名称
                "author": str,         # 作者名称
            },
            "error": str | None
        }
    
    注意：
    - 所有解析逻辑完全由 yt-dlp 处理
    - 返回的是视频直链（不下载文件到本地）
    - 如果提取失败，error 字段包含中文错误说明
    """
    result = {
        "success": False,
        "data": None,
        "error": None,
    }

    try:
        # 合并全局选项和格式排序选项
        opts = {**YDL_OPTS, **FORMAT_SORT_OPTS}
        logger.info(f"正在解析: {url[:80]}...")

        with get_ytdlp().YoutubeDL(opts) as ydl:
            # extract_info 是 yt-dlp 的核心方法
            # download=False 表示只解析不下载
            info = ydl.extract_info(url, download=False)

            if info is None:
                result["error"] = "视频解析失败，请检查链接是否有效"
                return result

            # 判断是否提取到的是播放列表
            if info.get("_type") == "playlist":
                entries = info.get("entries", [])
                if not entries:
                    result["error"] = "未找到视频，请检查链接"
                    return result
                # 取播放列表的第一个视频
                info = entries[0]
                if info is None:
                    result["error"] = "播放列表中无有效视频"
                    return result

            # ─── 提取视频直链 ───
            video_url = None
            formats = info.get("formats", [])

            # 策略1：从 formats 中寻找最佳无水印格式
            # yt-dlp 已按 format_sort 排序，第一个就是最佳
            if formats:
                # 查找非 m3u8（非分段）的视频格式
                for fmt in formats:
                    url = fmt.get("url", "")
                    protocol = fmt.get("protocol", "")
                    vcodec = fmt.get("vcodec", "none")
                    if url and protocol != "m3u8_native" and protocol != "m3u8" and vcodec != "none":
                        video_url = url
                        break

            # 策略2：使用请求格式的 URL
            if not video_url:
                video_url = info.get("url") or info.get("webpage_url")

            # ─── 提取元数据 ───
            title = info.get("title", "未命名视频")
            # 清理标题中的特殊字符
            title = re.sub(r"[^\w\s\-_—·,./()（）\u4e00-\u9fff]", "", title).strip()[:200]

            cover_url = info.get("thumbnail") or info.get("thumbnails", [{}])[0].get("url", "") if info.get("thumbnails") else ""
            duration = info.get("duration", 0) or 0

            # 平台识别
            extractor = info.get("extractor", "")
            platform_map = {
                "Douyin": "douyin",
                "Kuaishou": "kuaishou",
                "Xiaohongshu": "xiaohongshu",
                "Bilibili": "bilibili",
                "Weibo": "weibo",
                "Pipi": "pipixia",
                "Huoshan": "huoshan",
            }
            platform = "unknown"
            for key, val in platform_map.items():
                if key.lower() in extractor.lower():
                    platform = val
                    break

            author = info.get("uploader") or info.get("channel") or info.get("creator") or ""

            if not video_url:
                result["error"] = "未能提取到视频直链，该视频可能受平台限制"
                return result

            result["success"] = True
            result["data"] = {
                "title": title,
                "video_url": video_url,
                "cover_url": cover_url,
                "duration": float(duration),
                "platform": platform,
                "author": author,
            }
            logger.info(f"解析成功: {title[:40]}... ({platform})")

    except yt_dlp.utils.DownloadError as e:
        error_msg = str(e)
        if "Video unavailable" in error_msg:
            result["error"] = "视频不可用，可能已被删除或设为私密"
        elif "HTTP Error" in error_msg:
            result["error"] = "平台限制了访问，请稍后重试"
        elif "This video is only available" in error_msg:
            result["error"] = "该视频受平台限制，无法解析"
        else:
            result["error"] = f"视频解析失败: {error_msg[:150]}"
        logger.warning(f"DownloadError: {result['error']}")

    except yt_dlp.utils.ExtractorError as e:
        result["error"] = f"提取器异常: {str(e)[:150]}"
        logger.warning(f"ExtractorError: {result['error']}")

    except yt_dlp.utils.GeoRestrictedError:
        result["error"] = "该视频受地域限制，当前 IP 无法访问"

    except Exception as e:
        result["error"] = f"解析异常: {str(e)[:200]}"
        logger.error(f"Unexpected error: {str(e)[:300]}")

    return result


async def extract_video_info_async(url: str, timeout: int = 10) -> dict:
    """
    异步版核心解析函数。
    
    由于 yt-dlp 是同步库，使用 run_in_executor 放到线程池执行。
    设置超时防止请求卡死。
    
    Args:
        url: 短视频分享链接
        timeout: 超时秒数（默认 10 秒）
    """
    loop = asyncio.get_event_loop()

    try:
        result = await asyncio.wait_for(
            loop.run_in_executor(None, extract_video_info, url),
            timeout=timeout,
        )
        return result
    except asyncio.TimeoutError:
        logger.warning(f"解析超时 (>{timeout}s): {url[:60]}")
        return {
            "success": False,
            "data": None,
            "error": f"解析超时（超过 {timeout} 秒），请检查网络或稍后重试",
        }


# ═══════════════════════════════════════════════
#  第四部分：FastAPI 应用
# ═══════════════════════════════════════════════

# API 请求体模型
class ParseRequest(BaseModel):
    text: str = Field(
        ...,
        description="用户输入的文本（可以是纯链接或含文案/表情/换行的分享内容）",
        min_length=1,
        max_length=2000,
    )


# API 响应体模型
class ParseResponse(BaseModel):
    success: bool = Field(..., description="是否解析成功")
    data: Optional[dict] = Field(None, description="视频信息（成功时返回）")
    error: Optional[str] = Field(None, description="错误提示（失败时返回）")


youtube_dl = get_ytdlp().YoutubeDL


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用启动/关闭时的生命周期钩子"""
    logger.info("=" * 50)
    logger.info("短视频解析 API 启动中...")
    logger.info(f"yt-dlp 版本: {yt_dlp.version.__version__}")
    
    # 自动更新 yt-dlp 提取规则
    try:
        logger.info("正在检查 yt-dlp 更新...")
        result = subprocess.run(
            ["pip", "install", "--upgrade", "yt-dlp"],
            capture_output=True, text=True, timeout=30
        )
        if "Successfully installed" in result.stdout:
            new_version = result.stdout.split("Successfully installed")[-1].strip()
            logger.info(f"yt-dlp 已升级: {new_version}")
        else:
            logger.info("yt-dlp 已是最新版")
    except Exception as e:
        logger.warning(f"yt-dlp 自动更新失败（不影响运行）: {e}")
    
    # 确认最新版本
    import importlib
    importlib.reload(yt_dlp)
    logger.info(f"当前 yt-dlp 版本: {yt_dlp.version.__version__}")
    logger.info("Cookie 池就绪")
    logger.info("=" * 50)
    yield
    logger.info("API 已关闭")



app = FastAPI(
    title="短视频解析 API",
    description="基于 yt-dlp 的全平台短视频解析接口，支持抖音 / 快手 / 小红书 / B站 等",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS 允许所有来源（方便前端调用）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve frontend
@app.get("/")
async def index():
    idx = FRONTEND_DIR / "index.html"
    if idx.exists():
        return HTMLResponse(content=idx.read_text(encoding="utf-8"))
    return {"message": "API running - see /docs"}

# Static files (if needed)
from fastapi.staticfiles import StaticFiles
if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")



# ─── 中间件：IP 限流 ───

@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    """IP 限流中间件：每 IP 每分钟最多 10 次请求"""
    # 健康检查接口不限流
    if request.url.path == "/health":
        return await call_next(request)

    # 获取客户端 IP
    client_ip = request.client.host if request.client else "unknown"
    # 如果有 X-Forwarded-For 头（部署在反向代理后时）
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        client_ip = forwarded.split(",")[0].strip()

    if not rate_limiter.is_allowed(client_ip):
        remaining = rate_limiter.remaining(client_ip)
        logger.warning(f"IP 限流触发: {client_ip}")
        from fastapi.responses import JSONResponse
        return JSONResponse(
            status_code=429,
            content={
                "success": False,
                "data": None,
                "error": "请求过于频繁，每分钟最多 10 次，请稍后重试",
                "rate_limit": {
                    "remaining": remaining,
                    "reset_after_seconds": 60,
                },
            },
            headers={
                "X-RateLimit-Remaining": str(remaining),
                "X-RateLimit-Reset": str(int(time.time()) + 60),
                "Retry-After": "60",
            },
        )

    response = await call_next(request)
    return response


# ─── API 端点 ───

@app.get("/health")
async def health_check():
    """健康检查接口"""
    return {
        "status": "ok",
        "version": "1.0.0",
        "yt_dlp_version": yt_dlp.version.__version__,
        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
    }

@app.post("/api/cookie/import")
async def import_cookies(file: UploadFile = File(...)):
    """导入浏览器导出的 Cookie 文件"""
    content_bytes = await file.read()
    try:
        text = content_bytes.decode("utf-8")
    except:
        text = content_bytes.decode("gbk", errors="replace")
    
    success = cookie_pool.add_cookies(text)
    if success:
        stats = cookie_pool.get_pool_stats()
        return {"success": True, "message": f"Cookie 导入成功，当前共 {stats['total_groups']} 组", "stats": stats}
    else:
        raise HTTPException(400, "Cookie 格式无效，请确保是 Netscape 格式的 Cookie 文件")


@app.get("/api/cookie/status")
async def cookie_status():
    """查看 Cookie 池状态"""
    stats = cookie_pool.get_pool_stats()
    return {"success": True, "data": stats}


@app.post("/api/cookie/rotate")
async def rotate_cookie():
    """手动轮换 Cookie"""
    cookie_pool.rotate()
    stats = cookie_pool.get_pool_stats()
    return {"success": True, "message": f"已切换到第 {stats['current_index'] + 1} 组 Cookie", "stats": stats}


@app.post("/api/cookie/refresh")
async def refresh_cookies():
    """强制刷新 Cookie 过期检测"""
    cookie_pool.check_expiry(force=True)
    stats = cookie_pool.get_pool_stats()
    return {"success": True, "message": "Cookie 过期检测完成", "stats": stats}





@app.post("/api/video/parse", response_model=ParseResponse)
async def parse_video(request: ParseRequest):
    """
    解析短视频链接。
    
    抖音: 深度定制解析（Cookie 池 + 多级重试 + 反爬）
    其他平台: 常规 yt-dlp 解析
    
    返回无水印视频直链、标题、封面、时长。
    """
    text = request.text.strip()
    
    # Step 1: 提取链接
    url = extract_douyin_url(text)
    if not url:
        # 尝试通用 URL 提取（其他平台）
        # 尝试通用 URL 提取（从原文本中匹配所有 http 链接）
        generic_urls = re.findall(r'https?://[^\s"\'<>]+', text)
        if not generic_urls:
            return ParseResponse(
                success=False,
                data=None,
                error="未检测到有效的短视频链接（支持抖音/快手/小红书/B站等平台）",
            )
        url = generic_urls[0]
    
    # Step 2: 判断平台，选择解析器
    is_douyin = any(d in url.lower() for d in ["douyin.com", "iesdouyin.com"])
    
    if is_douyin:
        logger.info(f"Douyin URL -> deep parser: {url[:60]}...")
        result = await async_parse(url)
    else:
        logger.info(f"Other URL -> standard parser: {url[:60]}...")
        from processors.video_parser import extract_video_info_async as parse_other
        result = await parse_other(url, timeout=15)
    
    return ParseResponse(
        success=result["success"],
        data=result["data"],
        error=result.get("error"),
    )





# ═══════════════════════════════════════════
#  视频流式代理（解决手机播放和下载问题）
# ═══════════════════════════════════════════

@app.get("/api/video/stream")
async def stream_video(url: str = ""):
    """
    流式代理抖音视频（GET 方式，支持 <video> 标签直接引用）。
    用法: /api/video/stream?url=https://api-play.amemv.com/...
    """
    import httpx
    from urllib.parse import unquote
    from fastapi.responses import StreamingResponse, Response
    
    if not url:
        return Response("Missing url parameter", status_code=400)
    
    video_url = unquote(url)
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36",
        "Referer": "https://www.douyin.com/",
    }
    
    async def stream():
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                async with client.stream("GET", video_url, headers=headers, follow_redirects=True) as resp:
                    if resp.status_code != 200:
                        yield b""
                        return
                    async for chunk in resp.aiter_bytes(chunk_size=65536):
                        yield chunk
        except Exception:
            yield b""
    
    return StreamingResponse(
        stream(),
        media_type="video/mp4",
        headers={
            "Accept-Ranges": "bytes",
            "Cache-Control": "public, max-age=3600",
        }
    )


# ─── 直接运行 ───


def imread_unicode(path):
    buf = np.fromfile(str(path), dtype=np.uint8)
    return cv2.imdecode(buf, cv2.IMREAD_COLOR)


def imwrite_unicode(path, img):
    ext = str(path).rsplit(".", 1)[-1].lower()
    params = [cv2.IMWRITE_JPEG_QUALITY, 95]
    success, buf = cv2.imencode("." + ext, img, params)
    if success:
        with open(str(path), "wb") as f:
            f.write(buf.tobytes())
    return success


ALLOWED_IMG = {"png", "jpg", "jpeg", "webp", "bmp", "tiff", "tif"}
ALLOWED_VIDEO = {"mp4", "avi", "mov", "mkv", "webm", "wmv"}


def allowed_file(filename: str, formats: set) -> bool:
    ext = filename.rsplit(".", 1)[-1].lower()
    return ext in formats


def save_upload(file: UploadFile, subdir: Path) -> str:
    ext = file.filename.rsplit(".", 1)[-1].lower()
    name = f"{uuid.uuid4().hex}.{ext}"
    path = subdir / name
    with open(path, "wb") as f:
        f.write(file.file.read())
    return name


def _process_img(filename: str, processor) -> dict:
    src_path = UPLOAD_DIR / filename
    if not src_path.exists():
        raise HTTPException(404, "原图不存在")
    img = imread_unicode(src_path)
    if img is None:
        raise HTTPException(400, "图片读取失败")
    result = processor(img)
    out_name = f"out_{uuid.uuid4().hex}.png"
    out_path = RESULT_DIR / out_name
    imwrite_unicode(out_path, result)
    return {"filename": out_name, "path": f"/api/image/{out_name}"}




@app.post("/api/upload")
async def upload_image(file: UploadFile = File(...)):
    if not allowed_file(file.filename, ALLOWED_IMG):
        raise HTTPException(400, "不支持的文件格式")
    name = save_upload(file, UPLOAD_DIR)
    return {"filename": name, "path": f"/api/image/{name}"}


@app.get("/api/image/{name}")
async def get_image(name: str):
    for d in [UPLOAD_DIR, RESULT_DIR]:
        p = d / name
        if p.exists():
            return FileResponse(str(p))
    raise HTTPException(404, "图片不存在")

@app.get("/api/video/{name}")
async def get_video(name: str):
    for d in [RESULT_DIR, UPLOAD_DIR]:
        p = d / name
        if p.exists():
            return FileResponse(str(p))
    raise HTTPException(404, "视频不存在")


# ═══════════════════════════════════════
#  ⭐ Quality Inpaint (纹理合成修复)
# ═══════════════════════════════════════

@app.post("/api/inpaint-quality")
async def api_inpaint_quality(
    filename: str = Form(...),
    points_json: str = Form("[]"),
    radius: int = Form(5),
    use_auto: bool = Form(False),
):
    src_path = UPLOAD_DIR / filename
    if not src_path.exists():
        raise HTTPException(404, "原图不存在")
    img = imread_unicode(src_path)
    if img is None:
        raise HTTPException(400, "图片读取失败")

    if use_auto:
        mask = auto_detect_watermark(img)
        if np.sum(mask > 0) < 50:
            out_name = f"out_{uuid.uuid4().hex}.png"
            out_path = RESULT_DIR / out_name
            imwrite_unicode(out_path, img)
            return {"filename": out_name, "path": f"/api/image/{out_name}",
                    "watermark_found": False}
    else:
        points = json.loads(points_json) if points_json else []
        if not points:
            raise HTTPException(400, "请先涂抹水印区域")
        mask = create_mask_from_strokes(img.shape, points, radius)

    result = quality_inpaint(img, mask)
    out_name = f"out_{uuid.uuid4().hex}.png"
    out_path = RESULT_DIR / out_name
    imwrite_unicode(out_path, result)
    return {"filename": out_name, "path": f"/api/image/{out_name}",
            "watermark_found": not use_auto or np.sum(mask > 0) >= 50}


# ═══════════════════════════════════════
#  Manual Inpaint (涂抹修复)
# ═══════════════════════════════════════

@app.post("/api/inpaint")
async def api_inpaint(
    filename: str = Form(...),
    points_json: str = Form("[]"),
    radius: int = Form(5),
    method: str = Form("telea"),
    sharpen: float = Form(0.3),
    use_auto: bool = Form(False),
    use_quality: bool = Form(False),
):
    src_path = UPLOAD_DIR / filename
    if not src_path.exists():
        raise HTTPException(404, "原图不存在")
    img = imread_unicode(src_path)
    if img is None:
        raise HTTPException(400, "图片读取失败")

    # 自动检测去水印
    if use_auto:
        try:
            mask = auto_detect_watermark(img)
            pixel_count = int(np.sum(mask > 0)) if mask is not None else 0
            if pixel_count < 30:
                raise HTTPException(400, "未检测到明显水印区域，请尝试画笔手动涂抹")
            from processors.improved_inpaint import improved_inpaint
            result = improved_inpaint(img, mask, use_texture=True, use_color_match=True)
            out_name = "out_" + uuid.uuid4().hex + ".png"
            out_path = RESULT_DIR / out_name
            imwrite_unicode(out_path, result)
            return {"filename": out_name, "path": "/api/image/" + out_name}
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(500, "自动去水印失败: " + str(e))

    # 手动涂抹修复
    try:
        points = json.loads(points_json)
        if not points or len(points) < 3:
            raise HTTPException(400, "请先在图片上涂抹水印区域（至少涂抹3个点）")
        mask = create_mask_from_strokes(img.shape, points, radius)
        pixel_count = int(np.sum(mask > 0))
        if pixel_count < 10:
            raise HTTPException(400, "涂抹区域太小，请扩大涂抹范围")
        from processors.improved_inpaint import improved_inpaint
        result = improved_inpaint(img, mask, use_texture=True, use_color_match=True)
        out_name = "out_" + uuid.uuid4().hex + ".png"
        out_path = RESULT_DIR / out_name
        imwrite_unicode(out_path, result)
        return {"filename": out_name, "path": "/api/image/" + out_name}
    except json.JSONDecodeError:
        raise HTTPException(400, "涂抹数据格式错误")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, "修复失败: " + str(e))


# ════════════════════════════════

@app.post("/api/auto-remove")
async def api_auto_remove(
    filename: str = Form(...),
    radius: int = Form(5),
    method: str = Form("telea"),
    use_quality: bool = Form(False),
):
    src_path = UPLOAD_DIR / filename
    if not src_path.exists():
        raise HTTPException(404, "原图不存在")
    img = imread_unicode(src_path)
    if img is None:
        raise HTTPException(400, "图片读取失败")

    if use_quality:
        result, mask = auto_detect_and_inpaint_quality(img, radius)
    else:
        result, mask = auto_detect_and_inpaint(img, radius, method)

    found = bool(np.sum(mask > 0) >= 50)
    out_name = f"out_{uuid.uuid4().hex}.png"
    out_path = RESULT_DIR / out_name
    imwrite_unicode(out_path, result)
    return {"filename": out_name, "path": f"/api/image/{out_name}",
            "watermark_found": found}


def auto_detect_and_inpaint_quality(image, radius=5):
    """Auto detect + quality inpaint"""
    mask = auto_detect_watermark(image)
    if np.sum(mask > 0) < 50:
        return image.copy(), mask
    result = quality_inpaint(image, mask)
    return result, mask


@app.post("/api/auto-detect")
async def api_auto_detect(filename: str = Form(...)):
    src_path = UPLOAD_DIR / filename
    if not src_path.exists():
        raise HTTPException(404, "原图不存在")
    img = imread_unicode(src_path)
    if img is None:
        raise HTTPException(400, "图片读取失败")
    mask = auto_detect_watermark(img)
    overlay = img.copy()
    overlay[mask > 0] = [0, 0, 255]
    overlay = cv2.addWeighted(img, 0.5, overlay, 0.5, 0)
    out_name = f"mask_{uuid.uuid4().hex}.png"
    out_path = RESULT_DIR / out_name
    imwrite_unicode(out_path, overlay)
    has = bool(np.sum(mask > 0) > 50)
    return {"filename": out_name, "path": f"/api/image/{out_name}",
            "has_watermark": has, "mask_area": int(np.sum(mask > 0))}


# ═══════════════════════════════════════
#  Other Image Methods
# ═══════════════════════════════════════

@app.post("/api/remove-text")
async def api_remove_text(filename: str = Form(...), threshold: int = Form(40)):
    return _process_img(filename, lambda img: text_watermark_removal(img, threshold))


@app.post("/api/frequency")
async def api_frequency(filename: str = Form(...), sigma: float = Form(30.0)):
    return _process_img(filename, lambda img: frequency_filter(img, sigma))


@app.post("/api/remove-color")
async def api_remove_color(filename: str = Form(...),
                           lower_b: int = Form(0), lower_g: int = Form(0),
                           lower_r: int = Form(200), upper_b: int = Form(100),
                           upper_g: int = Form(100), upper_r: int = Form(255)):
    return _process_img(filename, lambda img: remove_by_color(
        img, [lower_b, lower_g, lower_r], [upper_b, upper_g, upper_r]))


@app.post("/api/remove-alpha")
async def api_remove_alpha(filename: str = Form(...), alpha_threshold: int = Form(200)):
    return _process_img(filename, lambda img: remove_alpha_watermark(img, alpha_threshold))



# ═══════════════════════════════════════
#  🔄 Format Conversion
# ═══════════════════════════════════════

@app.post("/api/convert/image")
async def api_convert_image(
    file: UploadFile = File(...),
    target_format: str = Form(...),
    quality: int = Form(95),
):
    target_format = target_format.lower().lstrip(".")
    if target_format not in {"png", "jpg", "jpeg", "webp", "bmp", "tiff"}:
        raise HTTPException(400, "不支持的输出格式")

    # Save uploaded file to temp
    ext = file.filename.rsplit(".", 1)[-1].lower()
    in_name = f"src_{uuid.uuid4().hex}.{ext}"
    in_path = UPLOAD_DIR / in_name
    with open(in_path, "wb") as f:
        f.write(file.file.read())

    out_name = f"conv_{uuid.uuid4().hex}.{target_format}"
    out_path = RESULT_DIR / out_name

    convert_image(str(in_path), str(out_path), quality)
    os.remove(str(in_path))

    return {"filename": out_name, "path": f"/api/image/{out_name}"}


@app.post("/api/convert/video")
async def api_convert_video(
    file: UploadFile = File(...),
    target_format: str = Form(...),
    quality: int = Form(23),
):
    target_format = target_format.lower().lstrip(".")
    if target_format not in VIDEO_FORMATS:
        raise HTTPException(400, "不支持的视频格式")

    ext = file.filename.rsplit(".", 1)[-1].lower()
    in_name = f"src_{uuid.uuid4().hex}.{ext}"
    in_path = UPLOAD_DIR / in_name
    with open(in_path, "wb") as f:
        f.write(file.file.read())

    out_name = f"conv_{uuid.uuid4().hex}.{target_format}"
    out_path = RESULT_DIR / out_name

    convert_video(str(in_path), str(out_path), quality=quality)
    os.remove(str(in_path))

    info = get_video_info(str(out_path))
    return {"filename": out_name, "path": f"/api/video/{out_name}", "info": info}


# ═══════════════════════════════════════




init_logger(BASE_DIR)
if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8001, reload=True)

if __name__ == "__main__":
    import uvicorn

    print(f"yt-dlp 版本: {yt_dlp.version.__version__}")
    print("启动 API 服务器: http://0.0.0.0:8000")
    print("文档地址: http://localhost:8000/docs")
    print("健康检查: http://localhost:8000/health")
    print()
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)






# ═══════════════════════════════════════
#  File Format Conversion (text encoding)
# ═══════════════════════════════════════

TEXT_ENCODINGS = [
    "utf-8", "gbk", "gb2312", "gb18030", "big5",
    "shift_jis", "euc-jp", "euc-kr", "latin-1",
    "ascii", "utf-16", "utf-16le", "utf-16be",
]

@app.post("/api/convert/file-encoding")
async def api_convert_encoding(
    file: UploadFile = File(...),
    source_encoding: str = Form("auto"),
    target_encoding: str = Form("utf-8"),
    line_endings: str = Form("auto"),
):
    """Convert text file encoding"""
    data = await file.read()
    
    if source_encoding == "auto":
        import chardet
        detected = chardet.detect(data)
        source_encoding = detected.get("encoding", "utf-8") or "utf-8"
        emap = {"gb2312": "gbk", "GB2312": "gbk", "ascii": "utf-8", "ANSI": "gbk", "windows-1252": "latin-1"}
        source_encoding = emap.get(source_encoding, source_encoding)
    
    try:
        text = data.decode(source_encoding, errors="replace")
    except (LookupError, UnicodeDecodeError) as e:
        raise HTTPException(400, f"Decode failed: {e}")
    
    # Line endings
    if line_endings == "crlf":
        text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "\r\n")
    elif line_endings == "lf":
        text = text.replace("\r\n", "\n").replace("\r", "\n")
    elif line_endings == "cr":
        text = text.replace("\r\n", "\n").replace("\n", "\r")
    
    try:
        encoded = text.encode(target_encoding, errors="replace")
    except (LookupError, UnicodeEncodeError) as e:
        raise HTTPException(400, f"Encode failed: {e}")
    
    orig_ext = file.filename.rsplit(".", 1)[-1] if "." in file.filename else "txt"
    out_name = f"enc_{uuid.uuid4().hex}.{orig_ext}"
    out_path = RESULT_DIR / out_name
    
    with open(str(out_path), "wb") as f:
        f.write(encoded)
    
    return {
        "filename": out_name,
        "path": f"/api/file/{out_name}",
        "source_encoding": source_encoding,
        "target_encoding": target_encoding,
        "file_size": len(encoded),
    }


@app.post("/api/convert/file-hash")
async def api_file_hash(file: UploadFile = File(...)):
    """Calculate file hashes"""
    import hashlib
    data = await file.read()
    return {
        "filename": file.filename,
        "size": len(data),
        "md5": hashlib.md5(data).hexdigest(),
        "sha1": hashlib.sha1(data).hexdigest(),
        "sha256": hashlib.sha256(data).hexdigest(),
    }


@app.post("/api/convert/file-info")
async def api_file_info(file: UploadFile = File(...)):
    """Get file info"""
    data = await file.read()
    ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
    
    info = {
        "filename": file.filename,
        "size": len(data),
        "size_display": _fmt_size(len(data)),
        "extension": ext,
        "mime_type": file.content_type or "unknown",
    }
    
    text_exts = {"txt", "csv", "json", "xml", "html", "htm", "css", "js", "py", "md", "log", "ini", "cfg", "conf"}
    if ext in text_exts:
        try:
            import chardet
            d = chardet.detect(data)
            info["encoding"] = d.get("encoding", "unknown")
            info["encoding_confidence"] = round(d.get("confidence", 0) * 100, 1)
        except:
            info["encoding"] = "unknown"
    
    return info




@app.post("/api/convert/audio")
async def api_convert_audio(
    file: UploadFile = File(...),
    target_format: str = Form("mp3"),
    quality: int = Form(192),
):
    """Convert audio format using FFmpeg"""
    target_format = target_format.lower().lstrip(".")
    supported = {"mp3", "wav", "ogg", "flac", "aac", "m4a", "wma"}
    if target_format not in supported:
        raise HTTPException(400, f"Unsupported audio format: {target_format}")
    
    import subprocess
    ext = file.filename.rsplit(".", 1)[-1].lower()
    in_name = f"audio_{uuid.uuid4().hex}.{ext}"
    in_path = UPLOAD_DIR / in_name
    data = await file.read()
    with open(str(in_path), "wb") as f:
        f.write(data)
    
    out_name = f"audio_{uuid.uuid4().hex}.{target_format}"
    out_path = RESULT_DIR / out_name
    
    # FFmpeg params per format
    codec_map = {
        "mp3": ("libmp3lame", "-b:a", str(quality) + "k"),
        "wav": ("pcm_s16le", None, None),
        "ogg": ("libvorbis", "-q:a", str(quality // 32)),
        "flac": ("flac", None, None),
        "aac": ("aac", "-b:a", str(quality) + "k"),
        "m4a": ("aac", "-b:a", str(quality) + "k"),
        "wma": ("wmav2", "-b:a", str(quality) + "k"),
    }
    
    acodec, bitrate_flag, bitrate_val = codec_map[target_format]
    
    cmd = ["ffmpeg", "-y", "-i", str(in_path), "-vn", "-c:a", acodec]
    if bitrate_flag and bitrate_val:
        cmd.extend([bitrate_flag, bitrate_val])
    cmd.append(str(out_path))
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if result.returncode != 0:
            raise HTTPException(400, f"Conversion failed: {result.stderr[:200]}")
    except subprocess.TimeoutExpired:
        raise HTTPException(400, "Conversion timeout (>120s)")
    finally:
        if in_path.exists():
            os.remove(str(in_path))
    
    if not out_path.exists():
        raise HTTPException(500, "Output file not created")
    
    return {"filename": out_name, "path": f"/api/file/{out_name}"}

def _fmt_size(size: int) -> str:
    for unit in ["B", "KB", "MB", "GB"]:
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


@app.get("/api/file/{name}")
async def get_file(name: str):
    """Serve converted files"""
    p = RESULT_DIR / name
    if p.exists():
        return FileResponse(str(p))
    raise HTTPException(404, "File not found")




@app.post("/api/convert/file-hash")
async def api_file_hash(file: UploadFile = File(...)):
    """Calculate file hashes (MD5, SHA1, SHA256)"""
    import hashlib
    data = await file.read()
    
    return {
        "filename": file.filename,
        "size": len(data),
        "md5": hashlib.md5(data).hexdigest(),
        "sha1": hashlib.sha1(data).hexdigest(),
        "sha256": hashlib.sha256(data).hexdigest(),
    }


@app.post("/api/convert/file-info")
async def api_file_info(file: UploadFile = File(...)):
    """Get file information"""
    data = await file.read()
    ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
    
    info = {
        "filename": file.filename,
        "size": len(data),
        "size_display": format_size(len(data)),
        "extension": ext,
        "mime_type": file.content_type or "unknown",
    }
    
    # Try to detect text encoding for text files
    text_exts = {"txt", "csv", "json", "xml", "html", "htm", "css", "js", "py", "md", "log", "ini", "cfg", "conf"}
    if ext in text_exts:
        try:
            import chardet
            detected = chardet.detect(data)
            info["encoding"] = detected.get("encoding", "unknown")
            info["encoding_confidence"] = round(detected.get("confidence", 0) * 100, 1)
        except:
            info["encoding"] = "unknown"
    
    return info


def format_size(size: int) -> str:
    """Format file size to human readable"""
    for unit in ["B", "KB", "MB", "GB"]:
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


@app.get("/api/file/{name}")
async def get_file(name: str):
    """Serve converted files"""
    p = RESULT_DIR / name
    if p.exists():
        return FileResponse(str(p))
    raise HTTPException(404, "File not found")

