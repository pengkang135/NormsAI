#!/bin/bash
# 启动定额浏览器
# Usage: ./start.sh [port]
#
# 在 output/ 目录下启动HTTP服务，自动打开浏览器

PORT=${1:-8080}
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUTPUT_DIR="$SCRIPT_DIR/output"

if [ ! -d "$OUTPUT_DIR" ]; then
    echo "错误: output/ 目录不存在"
    exit 1
fi

echo ""
echo "  定额浏览器已启动"
echo "  http://localhost:$PORT/norms_browser.html"
echo ""
echo "  按 Ctrl+C 停止服务"
echo ""

cd "$OUTPUT_DIR" && python -m http.server "$PORT" --bind 0.0.0.0
