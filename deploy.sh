#!/bin/bash
# 桦煜去水印 - 一键部署脚本（Ubuntu 20.04+ / Debian 11+）
set -e

PROJECT_DIR=$(pwd)
echo "项目目录: $PROJECT_DIR"

echo ""
echo "[1/5] 安装系统依赖..."
sudo apt-get update -qq
sudo apt-get install -y -qq python3 python3-pip python3-venv ffmpeg nginx curl

echo ""
echo "[2/5] 创建 Python 虚拟环境..."
if [ ! -d "venv" ]; then
    python3 -m venv venv
fi
source venv/bin/activate

echo ""
echo "[3/5] 安装 Python 依赖..."
pip install -r requirements.txt -q

echo ""
echo "[4/5] 安装 Playwright 浏览器..."
python -m playwright install chromium 2>/dev/null || true

echo ""
echo "[5/5] 创建开机自启服务..."
sudo tee /etc/systemd/system/huayu-parser.service << 'SERVICEEOF'
[Unit]
Description=桦煜去水印 API 服务
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/huayu-parser
ExecStart=/opt/huayu-parser/venv/bin/python fast_server.py
Restart=always
RestartSec=5
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
SERVICEEOF

echo ""
echo "========================================"
echo "  部署完成！"
echo "  服务管理:"
echo "    sudo systemctl start huayu-parser"
echo "    sudo systemctl stop huayu-parser"
echo "    sudo systemctl restart huayu-parser"
echo "    sudo systemctl status huayu-parser"
echo "    sudo journalctl -u huayu-parser -f"
echo ""
echo "  访问地址: http://你的服务器IP:8000"
echo "========================================"
