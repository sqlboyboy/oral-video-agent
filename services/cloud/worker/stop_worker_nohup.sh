#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/root/oral-video-agent-cloud-worker}"
PID_FILE="$APP_DIR/worker.pid"

if [[ ! -f "$PID_FILE" ]]; then
  echo "Worker pid file not found."
  exit 0
fi

PID="$(cat "$PID_FILE")"
if kill -0 "$PID" >/dev/null 2>&1; then
  kill "$PID"
  echo "Stopped worker $PID"
else
  echo "Worker $PID is not running."
fi
rm -f "$PID_FILE"
