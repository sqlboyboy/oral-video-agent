#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/root/oral-video-agent-cloud-worker}"
SERVICE_NAME="${SERVICE_NAME:-oral-video-autodl-worker.service}"

if [[ $EUID -ne 0 ]]; then
  echo "Please run as root on the AutoDL instance." >&2
  exit 1
fi

mkdir -p "$APP_DIR"

if [[ ! -f "$APP_DIR/autodl_worker.py" ]]; then
  echo "Missing $APP_DIR/autodl_worker.py" >&2
  echo "Copy autodl_worker.py into $APP_DIR before running this script." >&2
  exit 1
fi

if [[ ! -f "$APP_DIR/.env" ]]; then
  cat > "$APP_DIR/.env" <<'EOF'
CLOUD_API_BASE=https://api.example.com
WORKER_TOKEN=replace-with-worker-token
WORKER_ID=autodl-4090-1
WORKER_POLL_SECONDS=30
MANAGE_GPU_SERVICES=true
IDLE_SHUTDOWN_MINUTES=15
ENABLE_AUTODL_SHUTDOWN=false
SHUTDOWN_COMMAND='sudo shutdown -h now'
SIMULATE_RENDER_SECONDS=20
RENDER_COMMAND='/root/oral-video-agent-cloud-worker/run_render.sh {job_json} {output_path}'
LOCAL_RENDER_API_BASE=http://127.0.0.1:8000
LOCAL_RENDER_API_TIMEOUT_SECONDS=7200
EOF
  chmod 600 "$APP_DIR/.env"
  echo "Created $APP_DIR/.env. Edit WORKER_TOKEN before starting the service." >&2
fi

cat > "/etc/systemd/system/$SERVICE_NAME" <<EOF
[Unit]
Description=Oral Video Agent AutoDL Worker
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=$APP_DIR
EnvironmentFile=$APP_DIR/.env
ExecStart=/usr/bin/python3 $APP_DIR/autodl_worker.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable "$SERVICE_NAME"

echo "Installed $SERVICE_NAME."
echo "Next:"
echo "  1. Edit $APP_DIR/.env"
echo "  2. systemctl start $SERVICE_NAME"
echo "  3. journalctl -u $SERVICE_NAME -f"
