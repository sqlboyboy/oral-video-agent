#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/root/oral-video-agent-cloud-worker}"
PID_FILE="$APP_DIR/worker.pid"
LOG_FILE="$APP_DIR/worker.log"

cd "$APP_DIR"

if [[ -f "$APP_DIR/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$APP_DIR/.env"
  set +a
fi

if [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" >/dev/null 2>&1; then
  echo "Worker already running with pid $(cat "$PID_FILE")"
  exit 0
fi

nohup python3 "$APP_DIR/autodl_worker.py" >> "$LOG_FILE" 2>&1 &
echo $! > "$PID_FILE"
echo "Started worker with pid $(cat "$PID_FILE")"
echo "Log: $LOG_FILE"
