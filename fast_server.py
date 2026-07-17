import os, sys, json, io, uuid, re, time, asyncio
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
import cgi

# Add project to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

BASE_DIR = Path(__file__).parent
FRONTEND_DIR = BASE_DIR / "frontend"
UPLOAD_DIR = BASE_DIR / "uploads"
RESULT_DIR = BASE_DIR / "results"
UPLOAD_DIR.mkdir(exist_ok=True)
RESULT_DIR.mkdir(exist_ok=True)

# Import heavy modules lazily
cv2 = None
np = None
imread_unicode = None
imwrite_unicode = None
auto_detect_watermark = None
smart_inpaint = None
improved_inpaint = None
create_mask_from_strokes = None
convert_image = None
convert_video = None
get_video_info = None
frequency_filter = None
text_watermark_removal = None
remove_by_color = None
remove_alpha_watermark = None
async_parse = None
extract_douyin_url = None
cookie_pool = None
quality_inpaint = None

def lazy_import_cv():
    global cv2, np, imread_unicode, imwrite_unicode
    import cv2 as _cv2
    import numpy as _np
    cv2 = _cv2; np = _np
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

def lazy_import_ml():
    global auto_detect_watermark, smart_inpaint, improved_inpaint
    global create_mask_from_strokes, quality_inpaint
    lazy_import_cv()
    from processors.auto_detect import auto_detect_watermark as _ad
    from processors.smart_inpaint import smart_inpaint as _si
    from processors.improved_inpaint import improved_inpaint as _ii
    from processors.inpainting import create_mask_from_strokes as _cm
    from processors.quality_inpaint import quality_inpaint as _qi
    auto_detect_watermark = _ad; smart_inpaint = _si
    improved_inpaint = _ii; create_mask_from_strokes = _cm
    quality_inpaint = _qi

def lazy_import_convert():
    global convert_image, convert_video, get_video_info
    lazy_import_cv()
    from processors.converter import convert_image as _ci, convert_video as _cv, get_video_info as _gvi
    convert_image = _ci; convert_video = _cv; get_video_info = _gvi

def lazy_import_filter():
    global frequency_filter, text_watermark_removal, remove_by_color, remove_alpha_watermark
    lazy_import_cv()
    from processors.frequency import frequency_filter as _ff, text_watermark_removal as _tw
    from processors.color_filter import remove_by_color as _rc, remove_alpha_watermark as _ra
    frequency_filter = _ff; text_watermark_removal = _tw
    remove_by_color = _rc; remove_alpha_watermark = _ra

def simple_inpaint(img, mask, radius=3):
    """快速去水印：直接使用OpenCV TELEA算法，无复杂分析"""
    import cv2 as _cv2
    import numpy as _np
    m = (mask > 0).astype(_np.uint8) * 255
    k = _np.ones((3, 3), _np.uint8)
    m = _cv2.dilate(m, k, iterations=1)
    return _cv2.inpaint(img, m, radius, _cv2.INPAINT_TELEA)

def _detect_text_watermark(img):
    """检测水印：取梯度+阈值置信度最高的5%像素，硬限制最终mask<20%"""
    import cv2 as _cv2
    import numpy as _np
    h, w = img.shape[:2]
    gray = _cv2.cvtColor(img, _cv2.COLOR_BGR2GRAY) if len(img.shape) == 3 else img

    # ── 梯度强度 ──
    gx = _cv2.Sobel(gray, _cv2.CV_64F, 1, 0, ksize=3)
    gy = _cv2.Sobel(gray, _cv2.CV_64F, 0, 1, ksize=3)
    grad = _cv2.magnitude(gx, gy)

    # ── 自适应阈值 ──
    th = _np.zeros((h, w), dtype=_np.uint8)
    for bs, c in [(7, 2), (11, 3)]:
        ti = _cv2.adaptiveThreshold(gray, 255, _cv2.ADAPTIVE_THRESH_MEAN_C, _cv2.THRESH_BINARY_INV, bs, c)
        tn = _cv2.adaptiveThreshold(gray, 255, _cv2.ADAPTIVE_THRESH_MEAN_C, _cv2.THRESH_BINARY, bs, c)
        th = _cv2.bitwise_or(th, ti); th = _cv2.bitwise_or(th, tn)

    # ── 置信度评分并取前5% ──
    conf = grad.astype(_np.float32) * (th.astype(_np.float32) / 255.0)
    k = max(50, int(h * w * 0.05))
    flat = conf.flatten()
    idx = _np.argpartition(flat, -k)[-k:]
    mask = _np.zeros((h, w), dtype=_np.uint8)
    mask.flat[idx] = 255

    # ── 闭运算连接文字 ──
    kc = _cv2.getStructuringElement(_cv2.MORPH_ELLIPSE, (5, 5))
    mask = _cv2.morphologyEx(mask, _cv2.MORPH_CLOSE, kc, iterations=1)

    # ── 加入极亮/暗像素（严格阈值） ──
    bright = _np.where(gray > 240, 255, 0).astype(_np.uint8)
    dark = _np.where(gray < 10, 255, 0).astype(_np.uint8)
    mask = _cv2.bitwise_or(mask, bright)
    mask = _cv2.bitwise_or(mask, dark)

    # ── 移除＜5像素的孤立噪点 ──
    n, labels, stats, _ = _cv2.connectedComponentsWithStats(mask, 8)
    clean = _np.zeros((h, w), dtype=_np.uint8)
    for i in range(1, n):
        if stats[i, _cv2.CC_STAT_AREA] >= 5:
            clean[labels == i] = 255

    # ── 微膨胀 ──
    if _np.sum(clean > 0) >= 5:
        kd = _cv2.getStructuringElement(_cv2.MORPH_ELLIPSE, (3, 3))
        clean = _cv2.dilate(clean, kd, iterations=1)

    # ── 硬限制：如果mask超过15%，只保留最大的连通区域直到≤15% ──
    total = _np.sum(clean > 0)
    max_px = h * w * 0.15
    if total > max_px:
        n2, labs2, stats2, _ = _cv2.connectedComponentsWithStats(clean, 8)
        items = [(stats2[i, _cv2.CC_STAT_AREA], i) for i in range(1, n2)]
        items.sort(reverse=True)
        clamped = _np.zeros((h, w), dtype=_np.uint8)
        cum = 0
        for area, idx in items:
            if cum >= max_px: break
            clamped[labs2 == idx] = 255
            cum += area
        if _np.sum(clamped > 0) >= 10:
            return clamped

    return clean

def _limit_resolution(img, max_px=1080):
    """限制图片最大边长，加速处理"""
    import cv2 as _cv2
    h, w = img.shape[:2]
    scale = 1.0
    if max(h, w) > max_px:
        scale = max_px / max(h, w)
        new_w = int(w * scale)
        new_h = int(h * scale)
        img = _cv2.resize(img, (new_w, new_h), interpolation=_cv2.INTER_AREA)
    return img, scale


# 
def lazy_import_parse():
    global async_parse, extract_douyin_url, extract_platform_url, cookie_pool, parse_with_retry
    from processors.douyin_parser import async_parse as _ap, extract_douyin_url as _ed, extract_platform_url as _epu, cookie_pool as _cp
    async_parse = _ap; extract_douyin_url = _ed; extract_platform_url = _epu; cookie_pool = _cp
    from processors.douyin_parser import parse_with_retry as _pr
    parse_with_retry = _pr

ALLOWED_IMG = {"png", "jpg", "jpeg", "webp", "bmp", "tiff", "tif"}
ALLOWED_VIDEO = {"mp4", "avi", "mov", "mkv", "webm", "wmv"}

def parse_multipart(body, content_type):
    """Simple multipart form data parser"""
    # Extract boundary
    boundary = None
    for part in content_type.split(";"):
        part = part.strip()
        if part.startswith("boundary="):
            boundary = part[9:].strip('"').strip("'")
            break
    if not boundary:
        return {}
    boundary = b"--" + boundary.encode()
    parts = body.split(boundary)
    result = {}
    for p in parts:
        if p.strip() == b"" or p.strip() == b"--":
            continue
        if b"Content-Disposition" not in p:
            continue
        # Extract name
        name_match = re.search(rb'name="([^"]+)"', p)
        if not name_match:
            continue
        name = name_match.group(1).decode()
        # Check if file
        filename_match = re.search(rb'filename="([^"]*)"', p)
        if filename_match:
            filename = filename_match.group(1).decode()
            # Find file content (after double newline)
            header_end = p.find(b"\r\n\r\n")
            if header_end > 0:
                file_content = p[header_end + 4:]
                # Remove trailing boundary markers and whitespace
                file_content = file_content.rstrip(b"\r\n- ")
                result[name] = {"filename": filename, "content": file_content}
        else:
            # Regular field
            header_end = p.find(b"\r\n\r\n")
            if header_end > 0:
                value = p[header_end + 4:].decode("utf-8", errors="replace").strip()
                result[name] = value
    return result

def parse_urlencoded(body):
    result = {}
    for part in body.decode("utf-8").split("&"):
        if "=" in part:
            k, v = part.split("=", 1)
            from urllib.parse import unquote_plus
            result[unquote_plus(k)] = unquote_plus(v)
    return result

class FastHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/":
            self.serve_frontend()
        elif path == "/health":
            self.send_json({"status": "ok", "time": time.strftime("%Y-%m-%d %H:%M:%S")})
        elif path.startswith("/api/image/"):
            self.serve_image(path[11:])
        elif path.startswith("/api/video/stream"):
            self.serve_video_stream()
        elif path.startswith("/api/video/"):
            self.handle_api_video()
        else:
            self.send_error(404, "Not Found")
    
    def do_POST(self):
        path = self.path
        content_type = self.headers.get("Content-Type", "")
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length) if content_length > 0 else b""
        
        if "multipart/form-data" in content_type:
            data = parse_multipart(body, content_type)
        elif "application/json" in content_type:
            data = json.loads(body.decode("utf-8"))
        else:
            data = parse_urlencoded(body)
        
        if path == "/api/upload":
            self.handle_upload(data)
        elif path == "/api/inpaint":
            self.handle_inpaint(data)
        elif path == "/api/remove-text":
            self.handle_remove_text(data)
        elif path == "/api/frequency":
            self.handle_frequency(data)
        elif path == "/api/remove-color":
            self.handle_remove_color(data)
        elif path == "/api/remove-alpha":
            self.handle_remove_alpha(data)
        elif path == "/api/convert/image":
            self.handle_convert_image(data)
        elif path == "/api/convert/video":
            self.handle_convert_video(data)
        elif path == "/api/convert/audio":
            self.handle_convert_audio(data)
        elif path == "/api/convert/file-encoding":
            self.handle_convert_file_encoding(data)
        elif path == "/api/convert":
            self.handle_convert_generic(data)
        elif path == "/api/video/parse" or path == "/api/parse_url":
            try:
                self.handle_video_parse(data)
            except Exception as _e:
                self.send_json({"success": False, "error": "处理错误: " + str(_e)[:100]})
        else:
            self.send_error(404, "Not Found")
    
    def serve_frontend(self):
        idx = FRONTEND_DIR / "index.html"
        if idx.exists():
            content = idx.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
        else:
            self.send_json({"message": "Frontend not found"})
    
    def send_json(self, data, status=200):
        content = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(content)
    
    def send_error(self, code, message):
        self.send_json({"detail": message}, code)
    
    def serve_image(self, filename):
        fpath = RESULT_DIR / filename
        if not fpath.exists():
            fpath = UPLOAD_DIR / filename
        if not fpath.exists():
            return self.send_error(404, "File not found")
        content = fpath.read_bytes()
        ext = filename.rsplit(".", 1)[-1].lower()
        mime = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "webp": "image/webp", "bmp": "image/bmp"}.get(ext, "application/octet-stream")
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "public, max-age=3600")
        self.end_headers()
        self.wfile.write(content)
    
    def serve_video_stream(self):
        from urllib.parse import urlparse, parse_qs
        qs = parse_qs(self.path.split("?")[1] if "?" in self.path else "")
        url = qs.get("url", [""])[0]
        if not url:
            return self.send_error(400, "Missing url param")
        from urllib.parse import unquote
        url = unquote(url)
        import requests
        try:
            resp = requests.get(url, stream=True, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
            self.send_response(200)
            self.send_header("Content-Type", resp.headers.get("Content-Type", "video/mp4"))
            self.send_header("Content-Length", resp.headers.get("Content-Length", "0"))
            self.send_header("Accept-Ranges", "bytes")
            self.end_headers()
            for chunk in resp.iter_content(65536):
                if chunk:
                    self.wfile.write(chunk)
        except Exception as e:
            self.send_error(500, str(e))
    
    def handle_upload(self, data):
        lazy_import_cv()
        file_data = data.get("file")
        if not file_data or not isinstance(file_data, dict):
            return self.send_error(400, "No file uploaded")
        filename = file_data["filename"]
        content = file_data["content"]
        ext = filename.rsplit(".", 1)[-1].lower()
        if ext not in ALLOWED_IMG and ext not in ALLOWED_VIDEO:
            return self.send_error(400, "Unsupported file type")
        import uuid
        name = f"{uuid.uuid4().hex}.{ext}"
        save_path = UPLOAD_DIR / name
        save_path.write_bytes(content)
        self.send_json({"filename": name, "path": f"/api/image/{name}"})
    
    def handle_inpaint(self, data):
        lazy_import_cv()
        filename = data.get("filename", "")
        if not filename:
            return self.send_error(400, "缺少文件名")
        src_path = UPLOAD_DIR / filename
        if not src_path.exists():
            return self.send_error(404, "原图不存在")
        img = imread_unicode(src_path)
        if img is None:
            return self.send_error(400, "图片读取失败")

        import uuid
        use_auto = data.get("use_auto") == "true"
        if use_auto:
            try:
                mask = _detect_text_watermark(img)
                pixel_count = int(np.sum(mask > 0))
                mask_ratio = pixel_count / (img.shape[0] * img.shape[1]) if pixel_count > 0 else 0
                if pixel_count < 10:
                    return self.send_error(400, "未检测到有效水印区域，请尝试画笔手动涂抹")
                # 如果检测区域太大（超过25%），返回失败建议使用画笔
                if mask_ratio > 0.25:
                    return self.send_error(400, "图片复杂度过高，请使用画笔手动涂抹水印区域")
                proc_img, scale = _limit_resolution(img, 1080)
                if scale < 1.0:
                    m = cv2.resize(mask, (proc_img.shape[1], proc_img.shape[0]), interpolation=cv2.INTER_NEAREST)
                else:
                    m = mask
                result = simple_inpaint(proc_img, m, radius=3)
                if scale < 1.0:
                    result = cv2.resize(result, (img.shape[1], img.shape[0]), interpolation=cv2.INTER_CUBIC)
                out_name = f"out_" + uuid.uuid4().hex + ".png"
                out_path = RESULT_DIR / out_name
                imwrite_unicode(out_path, result)
                return self.send_json({"filename": out_name, "path": "/api/image/" + out_name})
            except Exception as e:
                return self.send_error(500, f"自动去水印失败: " + str(e))

        points_json = data.get("points_json", "[]")
        try:
            points = json.loads(points_json)
            if not points or len(points) < 3:
                return self.send_error(400, "请先在图片上涂抹水印区域（至少涂抹3个点）")
            radius = int(data.get("brush_radius", data.get("radius", "15")))
            # Lazy import for brush mask creation
            from processors.inpainting import create_mask_from_strokes
            mask = create_mask_from_strokes(img.shape, points, radius)
            pixel_count = int(np.sum(mask > 0))
            if pixel_count < 10:
                return self.send_error(400, "涂抹区域太小，请扩大涂抹范围")
            result = simple_inpaint(img, mask, radius=max(3, min(radius, 10)))
            out_name = f"out_" + uuid.uuid4().hex + ".png"
            out_path = RESULT_DIR / out_name
            imwrite_unicode(out_path, result)
            return self.send_json({"filename": out_name, "path": "/api/image/" + out_name})
        except json.JSONDecodeError:
            return self.send_error(400, "涂抹数据格式错误")
        except Exception as e:
            return self.send_error(500, f"修复失败: " + str(e))
    def handle_remove_text(self, data):
        lazy_import_ml()
        filename = data.get("filename", "")
        threshold = int(data.get("threshold", 40))
        src_path = UPLOAD_DIR / filename
        if not src_path.exists():
            return self.send_error(404, "原图不存在")
        img = imread_unicode(src_path)
        lazy_import_filter()
        result = text_watermark_removal(img, threshold)
        out_name = f"out_{uuid.uuid4().hex}.png"
        out_path = RESULT_DIR / out_name
        imwrite_unicode(out_path, result)
        return self.send_json({"filename": out_name, "path": f"/api/image/{out_name}"})
    
    def handle_frequency(self, data):
        lazy_import_ml()
        filename = data.get("filename", "")
        sigma = int(data.get("sigma", 15))
        src_path = UPLOAD_DIR / filename
        if not src_path.exists():
            return self.send_error(404, "原图不存在")
        img = imread_unicode(src_path)
        lazy_import_filter()
        result = frequency_filter(img, sigma)
        out_name = f"out_{uuid.uuid4().hex}.png"
        out_path = RESULT_DIR / out_name
        imwrite_unicode(out_path, result)
        return self.send_json({"filename": out_name, "path": f"/api/image/{out_name}"})
    
    def handle_remove_color(self, data):
        lazy_import_ml()
        filename = data.get("filename", "")
        lower = [int(data.get(f"lower_{c}", "0")) for c in ["b","g","r"]]
        upper = [int(data.get(f"upper_{c}", "255")) for c in ["b","g","r"]]
        src_path = UPLOAD_DIR / filename
        if not src_path.exists():
            return self.send_error(404, "原图不存在")
        img = imread_unicode(src_path)
        lazy_import_filter()
        result = remove_by_color(img, lower, upper)
        out_name = f"out_{uuid.uuid4().hex}.png"
        out_path = RESULT_DIR / out_name
        imwrite_unicode(out_path, result)
        return self.send_json({"filename": out_name, "path": f"/api/image/{out_name}"})
    
    def handle_remove_alpha(self, data):
        lazy_import_ml()
        filename = data.get("filename", "")
        threshold = int(data.get("alpha_threshold", 200))
        src_path = UPLOAD_DIR / filename
        if not src_path.exists():
            return self.send_error(404, "原图不存在")
        img = imread_unicode(src_path)
        lazy_import_filter()
        result = remove_alpha_watermark(img, threshold)
        out_name = f"out_{uuid.uuid4().hex}.png"
        out_path = RESULT_DIR / out_name
        imwrite_unicode(out_path, result)
        return self.send_json({"filename": out_name, "path": f"/api/image/{out_name}"})
    
    def handle_convert_image(self, data):
        lazy_import_convert()
        file_data = data.get("file")
        if not file_data or not isinstance(file_data, dict):
            return self.send_error(400, "No file uploaded")
        filename = file_data["filename"]
        content = file_data["content"]
        target_format = data.get("target_format", data.get("format", "png"))
        quality = int(data.get("quality", "95"))
        import tempfile, uuid
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=f".{filename.rsplit('.',1)[-1]}")
        tmp.write(content); tmp.close()
        out_name = f"conv_{uuid.uuid4().hex}.{target_format}"
        out_path = str(RESULT_DIR / out_name)
        try:
            convert_image(tmp.name, out_path, quality)
            self.send_json({"path": f"/api/image/{out_name}", "filename": out_name})
        finally:
            os.unlink(tmp.name)
    
    def handle_convert_video(self, data):
        lazy_import_convert()
        file_data = data.get("file")
        if not file_data or not isinstance(file_data, dict):
            return self.send_error(400, "No file uploaded")
        target_format = data.get("target_format", data.get("format", "mp4"))
        quality = int(data.get("quality", "23"))
        import tempfile, uuid
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=f".{file_data['filename'].rsplit('.',1)[-1]}")
        tmp.write(file_data["content"]); tmp.close()
        out_name = f"conv_{uuid.uuid4().hex}.{target_format}"
        out_path = str(RESULT_DIR / out_name)
        try:
            convert_video(tmp.name, out_path, quality)
            self.send_json({"path": f"/api/image/{out_name}", "filename": out_name})
        finally:
            os.unlink(tmp.name)
    
    def handle_convert_audio(self, data):
        file_data = data.get("file")
        if not file_data or not isinstance(file_data, dict):
            return self.send_error(400, "No file uploaded")
        target_format = data.get("target_format", "mp3")
        quality = data.get("quality", "192")
        import tempfile, subprocess
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=f".{file_data['filename'].rsplit('.',1)[-1]}")
        tmp.write(file_data["content"]); tmp.close()
        import uuid
        out_name = f"audio_{uuid.uuid4().hex}.{target_format}"
        out_path = RESULT_DIR / out_name
        try:
            cmd = ["ffmpeg", "-y", "-i", tmp.name, "-b:a", f"{quality}k", str(out_path)]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            if result.returncode == 0:
                self.send_json({"path": f"/api/image/{out_name}", "filename": out_name})
            else:
                self.send_error(500, f"转换失败: {result.stderr[:200]}")
        except Exception as e:
            self.send_error(500, str(e))
        finally:
            os.unlink(tmp.name)
    
    def handle_convert_file_encoding(self, data):
        file_data = data.get("file")
        if not file_data or not isinstance(file_data, dict):
            return self.send_error(400, "No file uploaded")
        source_encoding = data.get("source_encoding", "auto")
        target_encoding = data.get("target_encoding", "utf-8")
        import uuid
        content = file_data["content"]
        try:
            if source_encoding == "auto":
                import chardet
                detected = chardet.detect(content)
                source_encoding = detected.get("encoding", "utf-8")
            decoded = content.decode(source_encoding)
            encoded = decoded.encode(target_encoding)
            out_name = f"text_{uuid.uuid4().hex}.txt"
            out_path = RESULT_DIR / out_name
            out_path.write_bytes(encoded)
            self.send_json({"path": f"/api/image/{out_name}", "filename": out_name})
        except Exception as e:
            self.send_error(500, f"编码转换失败: {str(e)}")
    
    def handle_convert_generic(self, data):
        file_data = data.get("file")
        if not file_data or not isinstance(file_data, dict):
            return self.send_error(400, "No file uploaded")
        filename = file_data.get("filename", "")
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        target = data.get("format", data.get("target_format", "")).lower()
        
        # Auto-detect category from source file extension or target format
        img_exts = {"png", "jpg", "jpeg", "webp", "bmp", "tiff", "tif", "gif"}
        video_exts = {"mp4", "avi", "mov", "mkv", "webm", "wmv", "gif"}
        audio_exts = {"mp3", "wav", "aac", "ogg", "flac", "wma"}
        text_enc = {"utf8", "utf-8", "gbk", "gb2312", "big5"}
        
        if target in text_enc:
            data["target_encoding"] = target
            return self.handle_convert_file_encoding(data)
        elif target in audio_exts or ext in audio_exts:
            data["target_format"] = target if target in audio_exts else "mp3"
            return self.handle_convert_audio(data)
        elif target in video_exts or ext in video_exts:
            data["target_format"] = target if target in video_exts else "mp4"
            return self.handle_convert_video(data)
        elif target in img_exts or ext in img_exts:
            data["target_format"] = target if target in img_exts else "png"
            return self.handle_convert_image(data)
        else:
            return self.send_error(400, "不支持的文件格式: " + target)

    def handle_video_parse(self, data):
        text = data.get("url", data.get("text", "")) if isinstance(data, dict) else ""
        if not text:
            return self.send_error(400, "请粘贴分享链接")
        lazy_import_parse()
        try:
            # 先提取纯净链接
            platform, url = extract_platform_url(text)
            if not url:
                self.send_json({"success": False, "error": "未找到有效链接，请检查输入"})
                return
            import threading
            _r = {}
            def _do():
                try: _r["r"] = parse_with_retry(url)
                except Exception as e: _r["e"] = e
            t = threading.Thread(target=_do, daemon=True)
            t.start()
            t.join(timeout=20)
            if t.is_alive():
                self.send_json({"success": False, "error": "解析超时，请检查链接是否有效"})
                return
            if "e" in _r:
                self.send_json({"success": False, "error": "解析失败: " + str(_r["e"])[:100]})
                return
            result = _r.get("r")
            if result and result.get("success"):
                data = result.get("data", {})
                response = {
                    "success": True,
                    "url": data.get("video_url", ""),
                    "video_url": data.get("video_url", ""),
                    "title": data.get("title", ""),
                    "cover_url": data.get("cover_url", ""),
                    "duration": data.get("duration", 0),
                    "platform": platform or data.get("platform", ""),
                    "author": data.get("author", ""),
                    "content_type": data.get("content_type", "video"),
                }
                self.send_json(response)
            else:
                err = result.get("error", "解析失败") if result else "解析失败"
                self.send_json({"success": False, "error": err})
        except Exception as e:
            self.send_json({"success": False, "error": "解析出错: " + str(e)[:100]})
    
    def log_message(self, format, *args):
        # Suppress default logging
        pass

def prewarm():
    """Make a dummy connection to pre-warm the TCP stack"""
    import socket, threading
    time.sleep(0.5)
    try:
        s = socket.socket()
        s.connect(("127.0.0.1", 8000))
        s.send(b"GET /health HTTP/1.0\r\n\r\n")
        s.recv(1024)
        s.close()
    except:
        pass

def preload_models():
    """Preload heavy ML models on server startup"""
    print("[Server] Preloading ML models...")
    try:
        from processors.improved_inpaint import improved_inpaint
        from processors.lama_inpaint import warmup, is_lama_available
        if is_lama_available():
            warmup()
        print("[Server] ML models loaded")
    except Exception as e:
        print(f"[Server] Preload warning: {e}")

if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    server = ThreadingHTTPServer(("0.0.0.0", port), FastHandler)
    print(f"Server running on http://0.0.0.0:{port}")
    # Preload models in background thread
    import threading
    t = threading.Thread(target=preload_models, daemon=True)
    t.start()
    server.serve_forever()

