#!/usr/bin/env bash
# 本地起一个静态服务，把案头跑起来（零依赖，只要有 python3）
set -euo pipefail
cd "$(dirname "$0")"
if [ ! -d dist ]; then
  echo "还没构建。先跑：npm install && npm run build"
  exit 1
fi
PORT="${1:-5173}"
echo "案头 → http://localhost:$PORT"
echo "在 Chrome 里打开后：地址栏右侧的「安装」图标 → 装到桌面。Ctrl+C 停止。"
cd dist && python3 -m http.server "$PORT" --bind 127.0.0.1
