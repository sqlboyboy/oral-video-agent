#!/usr/bin/env bash
set -euo pipefail

STAGING_DIR="${1:?Usage: deploy_android_update_backend.sh <staging-dir> [deploy-root]}"
DEPLOY_ROOT="${2:-/opt/oral-video-agent/cloud}"
PUBLIC_BASE_URL="${CLOUD_PUBLIC_BASE_URL:?Set CLOUD_PUBLIC_BASE_URL to your cloud API URL}"
TIMESTAMP="$(date -u +%Y%m%d-%H%M%S)"

for file in app/main.py app/settings.py app/store.py; do
  if [[ ! -f "$STAGING_DIR/$file" ]]; then
    echo "Missing staged file: $file" >&2
    exit 2
  fi
done

mkdir -p "$DEPLOY_ROOT/backups/security-update-$TIMESTAMP"
cp "$DEPLOY_ROOT/app/main.py" \
  "$DEPLOY_ROOT/backups/security-update-$TIMESTAMP/main.py"
cp "$DEPLOY_ROOT/app/settings.py" \
  "$DEPLOY_ROOT/backups/security-update-$TIMESTAMP/settings.py"
cp "$DEPLOY_ROOT/app/store.py" \
  "$DEPLOY_ROOT/backups/security-update-$TIMESTAMP/store.py"
install -m 0644 "$STAGING_DIR/app/main.py" "$DEPLOY_ROOT/app/main.py"
install -m 0644 "$STAGING_DIR/app/settings.py" "$DEPLOY_ROOT/app/settings.py"
install -m 0644 "$STAGING_DIR/app/store.py" "$DEPLOY_ROOT/app/store.py"

ENV_FILE="$DEPLOY_ROOT/deploy/.env"
set_env() {
  local key="$1"
  local value="$2"
  if grep -q "^${key}=" "$ENV_FILE"; then
    sed -i "s|^${key}=.*|${key}=${value}|" "$ENV_FILE"
  else
    printf '%s=%s\n' "$key" "$value" >>"$ENV_FILE"
  fi
}
set_env CLOUD_PUBLIC_BASE_URL "$PUBLIC_BASE_URL"
set_env ADMIN_COOKIE_SECURE true
set_env ANDROID_RELEASE_DIR /data/releases/android
set_env COS_DOWNLOAD_CONFIRM_DELETE_DELAY_HOURS 24

cd "$DEPLOY_ROOT/deploy"
docker compose up -d --build cloud-api scheduler

for _ in $(seq 1 30); do
  if curl -fsS http://127.0.0.1:18080/api/health >/dev/null; then
    curl -fsS "$PUBLIC_BASE_URL/api/health"
    echo
    exit 0
  fi
  sleep 2
done

docker compose logs --tail=120 cloud-api
echo "Cloud API did not become healthy" >&2
exit 3
