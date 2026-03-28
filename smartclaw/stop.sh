#!/bin/bash
# SmartClaw 停止脚本
# 用法: ./stop.sh

set -e

PIDFILE="${HOME}/.smartclaw/smartclaw.pid"

if [ -f "$PIDFILE" ]; then
    PID=$(cat "$PIDFILE")
    if kill -0 "$PID" 2>/dev/null; then
        echo "🛑 Stopping SmartClaw (PID: $PID)..."
        kill "$PID"
        # 等待进程退出（最多 10 秒）
        for i in $(seq 1 10); do
            if ! kill -0 "$PID" 2>/dev/null; then
                echo "✅ SmartClaw stopped"
                rm -f "$PIDFILE"
                exit 0
            fi
            sleep 1
        done
        # 超时强制杀
        echo "⚠️  Timeout, force killing..."
        kill -9 "$PID" 2>/dev/null || true
        rm -f "$PIDFILE"
        echo "✅ SmartClaw force stopped"
    else
        echo "⚠️  PID $PID not running, cleaning up pidfile"
        rm -f "$PIDFILE"
    fi
else
    # 没有 pidfile，尝试按进程名查找
    PIDS=$(pgrep -f "smartclaw.serve" 2>/dev/null || true)
    if [ -n "$PIDS" ]; then
        echo "🛑 Stopping SmartClaw processes: $PIDS"
        echo "$PIDS" | xargs kill 2>/dev/null || true
        sleep 2
        echo "✅ SmartClaw stopped"
    else
        echo "ℹ️  SmartClaw is not running"
    fi
fi
