#!/bin/bash
# SmartClaw 一键启动脚本
# 用法: ./start.sh [gateway|cli]
#   gateway (默认) — 启动 API Gateway + Debug UI (http://localhost:8000)
#   cli             — 启动交互式 CLI

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# 加载 .env
if [ -f .env ]; then
    export $(grep -v '^#' .env | xargs)
fi

MODE="${1:-gateway}"

echo ""
echo "🦀 SmartClaw"
echo "================================"

# 检查 uv
if ! command -v uv &>/dev/null; then
    echo "❌ uv 未安装，请先安装: https://docs.astral.sh/uv/"
    exit 1
fi

# 同步依赖（静默）
uv sync --quiet 2>/dev/null || true

case "$MODE" in
    gateway|serve|web)
        echo "模式:    API Gateway + Debug UI"
        echo "地址:    http://localhost:8000"
        echo "Swagger: http://localhost:8000/docs"
        echo "================================"
        echo ""
        uv run python -m smartclaw.serve
        ;;
    cli)
        echo "模式:    交互式 CLI"
        echo "================================"
        echo ""
        uv run python -m smartclaw.cli
        ;;
    *)
        echo "用法: ./start.sh [gateway|cli]"
        echo "  gateway — API Gateway + Debug UI (默认)"
        echo "  cli     — 交互式 CLI"
        exit 1
        ;;
esac
