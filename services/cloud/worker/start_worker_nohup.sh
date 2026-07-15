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

worker_pid_is_valid() {
  local pid="${1:-}"
  local cmdline=""
  [[ "$pid" =~ ^[0-9]+$ ]] || return 1
  [[ -r "/proc/$pid/cmdline" ]] || return 1
  cmdline="$(tr '\0' ' ' < "/proc/$pid/cmdline" 2>/dev/null || true)"
  [[ "$cmdline" == *"$APP_DIR/autodl_worker.py"* ]]
}

find_running_worker() {
  local proc_dir=""
  local pid=""
  for proc_dir in /proc/[0-9]*; do
    pid="${proc_dir##*/}"
    if worker_pid_is_valid "$pid"; then
      echo "$pid"
      return 0
    fi
  done
  return 1
}

pid=""
if [[ -f "$PID_FILE" ]]; then
  read -r pid < "$PID_FILE" || true
fi
if worker_pid_is_valid "$pid"; then
  echo "Worker already running with pid $pid"
  exit 0
fi

existing_pid="$(find_running_worker || true)"
if [[ -n "$existing_pid" ]]; then
  echo "$existing_pid" > "$PID_FILE"
  echo "Recovered running worker with pid $existing_pid"
  exit 0
fi

if [[ -f "$PID_FILE" ]]; then
  echo "Removing stale worker pid file (pid=${pid:-unknown})"
  rm -f "$PID_FILE"
fi

nohup python3 "$APP_DIR/autodl_worker.py" >> "$LOG_FILE" 2>&1 &
new_pid=$!
echo "$new_pid" > "$PID_FILE"
sleep 1
if ! worker_pid_is_valid "$new_pid"; then
  rm -f "$PID_FILE"
  echo "Worker failed to stay running; inspect $LOG_FILE" >&2
  exit 1
fi
echo "Started worker with pid $new_pid"
echo "Log: $LOG_FILE"
