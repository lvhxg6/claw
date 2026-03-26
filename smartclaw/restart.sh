#!/bin/bash
# SmartClaw 重启脚本
# 用法: ./restart.sh [gateway|cli]

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "🔄 Restarting SmartClaw..."
"$SCRIPT_DIR/stop.sh"
sleep 1
"$SCRIPT_DIR/start.sh" "${1:-gateway}"
