import json, time, os
from datetime import datetime

LOG_DIR = None

def init_logger(base_dir):
    global LOG_DIR
    LOG_DIR = os.path.join(base_dir, "logs")
    os.makedirs(LOG_DIR, exist_ok=True)

def log_watermark_operation(video_name, method, duration, video_params=None, success=True, error=None):
    global LOG_DIR
    if LOG_DIR is None: return
    entry = {
        "timestamp": datetime.now().isoformat(),
        "video": video_name,
        "method": method,
        "duration_seconds": round(duration, 2),
        "success": success
    }
    if video_params: entry.update(video_params)
    if error: entry["error"] = str(error)
    log_file = os.path.join(LOG_DIR, "watermark.log")
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry

def get_logs(count=10):
    if LOG_DIR is None: return []
    log_file = os.path.join(LOG_DIR, "watermark.log")
    if not os.path.exists(log_file): return []
    logs = []
    with open(log_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try: logs.append(json.loads(line))
                except: pass
    return logs[-count:]
