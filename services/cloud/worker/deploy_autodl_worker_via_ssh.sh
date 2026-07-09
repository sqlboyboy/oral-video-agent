#!/usr/bin/env bash
set -euo pipefail

required() {
  local name="$1"
  if [[ -z "${!name:-}" ]]; then
    echo "$name is required" >&2
    exit 1
  fi
}

required AUTODL_HOST
required AUTODL_PORT
required AUTODL_USER
required AUTODL_PASSWORD
required CLOUD_API_BASE
required WORKER_TOKEN

WORKER_ID="${WORKER_ID:-autodl-4090-1}"
IDLE_SHUTDOWN_MINUTES="${IDLE_SHUTDOWN_MINUTES:-15}"
ENABLE_AUTODL_SHUTDOWN="${ENABLE_AUTODL_SHUTDOWN:-false}"
REMOTE_DIR="${REMOTE_DIR:-/root/oral-video-agent-cloud-worker}"

if ! command -v sshpass >/dev/null 2>&1; then
  echo "sshpass is required on the machine running this script." >&2
  exit 1
fi

SSH_OPTS=(
  -o StrictHostKeyChecking=no
  -o UserKnownHostsFile=/dev/null
  -p "$AUTODL_PORT"
)

SCP_OPTS=(
  -o StrictHostKeyChecking=no
  -o UserKnownHostsFile=/dev/null
  -P "$AUTODL_PORT"
)

sshpass -p "$AUTODL_PASSWORD" ssh "${SSH_OPTS[@]}" "$AUTODL_USER@$AUTODL_HOST" \
  "mkdir -p '$REMOTE_DIR'"

sshpass -p "$AUTODL_PASSWORD" scp "${SCP_OPTS[@]}" \
  autodl_worker.py run_render.py run_render.sh \
  install_autodl_worker.sh start_worker_nohup.sh stop_worker_nohup.sh \
  "$AUTODL_USER@$AUTODL_HOST:$REMOTE_DIR/"

sshpass -p "$AUTODL_PASSWORD" ssh "${SSH_OPTS[@]}" "$AUTODL_USER@$AUTODL_HOST" \
  "cat > '$REMOTE_DIR/.env' <<EOF
CLOUD_API_BASE=$CLOUD_API_BASE
WORKER_TOKEN=$WORKER_TOKEN
WORKER_ID=$WORKER_ID
WORKER_POLL_SECONDS=30
MANAGE_GPU_SERVICES=${MANAGE_GPU_SERVICES:-true}
IDLE_SHUTDOWN_MINUTES=$IDLE_SHUTDOWN_MINUTES
ENABLE_AUTODL_SHUTDOWN=$ENABLE_AUTODL_SHUTDOWN
SHUTDOWN_COMMAND='sudo shutdown -h now'
SIMULATE_RENDER_SECONDS=20
RENDER_COMMAND='$REMOTE_DIR/run_render.sh {job_json} {output_path}'
LOCAL_RENDER_API_BASE=http://127.0.0.1:8000
LOCAL_RENDER_API_TIMEOUT_SECONDS=7200
EOF
chmod 600 '$REMOTE_DIR/.env'
chmod +x '$REMOTE_DIR/'*.sh
cd '$REMOTE_DIR'
if command -v systemctl >/dev/null 2>&1 && [[ \"\$(ps -p 1 -o comm=)\" == \"systemd\" ]]; then
  bash install_autodl_worker.sh
  systemctl start oral-video-autodl-worker.service
  systemctl --no-pager --full status oral-video-autodl-worker.service
else
  echo 'systemd is not available; starting worker with nohup.'
  bash stop_worker_nohup.sh || true
  bash start_worker_nohup.sh
  sleep 2
  tail -n 40 worker.log || true
fi"
