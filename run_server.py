import time, requests, threading, subprocess, sys
import uvicorn
from main import app

def keep_warm():
    """Keep server warm by making periodic requests"""
    time.sleep(8)  # wait for server to start
    while True:
        try:
            requests.get("http://localhost:8000/health", timeout=5)
        except:
            pass
        time.sleep(30)

if __name__ == "__main__":
    t = threading.Thread(target=keep_warm, daemon=True)
    t.start()
    uvicorn.run(app, host="0.0.0.0", port=8000)
