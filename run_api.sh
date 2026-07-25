#!/bin/bash
# API 服务启动脚本
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# 加载环境变量
if [ -f config/.env ]; then
    export $(grep -v '^#' config/.env | xargs)
fi

# 安装 flask（如果没有）
pip3 install --break-system-packages flask 2>/dev/null || true

echo "Starting Crypto News API on port ${API_PORT:-8080}..."
python3 api/server.py

