FROM python:3.12-slim

WORKDIR /app

# 安装系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libnss3 \
    libnspr4 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libdbus-1-3 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libpango-1.0-0 \
    libcairo2 \
    libasound2 \
    && rm -rf /var/lib/apt/lists/*

# 安装 Python 依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制代码
COPY . .

# 启动

# Download LaMa AI inpainting model (88MB, needed for best quality inpainting)
RUN python -c "import os,urllib.request; p='processors/models/lama.onnx'; urllib.request.urlretrieve('https://github.com/opencv/opencv_zoo/raw/main/models/inpainting_lama/inpainting_lama_2025jan.onnx', p) if not os.path.exists(p) else None"

CMD ["python", "fast_server.py"]
