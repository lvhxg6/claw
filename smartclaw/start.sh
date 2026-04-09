#!/bin/bash
# SmartClaw 一键启动脚本
# 用法: ./start.sh [gateway|cli]
#   gateway (默认) — 启动 API Gateway + Debug UI (http://localhost:8000)
#   cli             — 启动交互式 CLI

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# Runtime paths (sandbox-friendly defaults)
RUNTIME_DIR="${SMARTCLAW_RUNTIME_DIR:-${SCRIPT_DIR}/.smartclaw}"
PIDFILE="${SMARTCLAW_PIDFILE:-${RUNTIME_DIR}/smartclaw.pid}"

# uv cache path (avoid ~/.cache permission issues in restricted envs)
if [ -z "${UV_CACHE_DIR:-}" ]; then
    export UV_CACHE_DIR="${SCRIPT_DIR}/.uv-cache"
fi
mkdir -p "${UV_CACHE_DIR}" "${RUNTIME_DIR}"

# 加载 .env
if [ -f .env ]; then
    set -a
    . ./.env
    set +a
fi

MODE="${1:-gateway}"

# 日志路径（默认按天写入 smartclaw/logs）
LOG_DIR="${SMARTCLAW_LOG_DIR:-${SCRIPT_DIR}/logs}"
LOG_DATE="$(date +%Y-%m-%d)"
LOG_FILE="${SMARTCLAW_LOG_FILE:-${LOG_DIR}/smartclaw-${LOG_DATE}.log}"
mkdir -p "$LOG_DIR"
touch "$LOG_FILE"

# 将 start.sh 与服务输出统一写入日志文件（同时保留终端输出）
exec > >(tee -a "$LOG_FILE") 2>&1

echo ""
echo "🦀 SmartClaw"
echo "================================"
echo "日志:    $LOG_FILE"

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
        uv run python -m smartclaw.serve &
        echo $! > "$PIDFILE"
        echo "PID:     $(cat "$PIDFILE")"
        wait
        rm -f "$PIDFILE"
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
