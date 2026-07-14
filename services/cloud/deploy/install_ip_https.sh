#!/usr/bin/env bash
set -euo pipefail

PUBLIC_IP="${1:?Usage: install_ip_https.sh <public-ip>}"
if [[ ! "$PUBLIC_IP" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}$ ]]; then
  echo "Invalid IPv4 address" >&2
  exit 2
fi

CERTBOT_VENV=/opt/oral-video-certbot
CERTBOT="$CERTBOT_VENV/bin/certbot"
WEBROOT=/var/www/certbot
NGINX_SITE=/etc/nginx/sites-available/oral-video-cloud.conf

apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
  python3-venv ca-certificates
if [[ ! -x "$CERTBOT_VENV/bin/python" ]]; then
  python3 -m venv "$CERTBOT_VENV"
fi
"$CERTBOT_VENV/bin/pip" install --upgrade pip
"$CERTBOT_VENV/bin/pip" install --upgrade 'certbot>=5.4,<6'

install -d -m 0755 "$WEBROOT/.well-known/acme-challenge"
rm -f /etc/nginx/stream-conf.d/oral-video-cloud-port80.conf
if [[ -f "$NGINX_SITE" && ! -f "$NGINX_SITE.pre-ip-https" ]]; then
  cp "$NGINX_SITE" "$NGINX_SITE.pre-ip-https"
fi

cat >"$NGINX_SITE" <<EOF
server {
    listen 80 default_server;
    listen [::]:80 default_server;
    server_name $PUBLIC_IP _;

    location ^~ /.well-known/acme-challenge/ {
        root $WEBROOT;
        default_type text/plain;
    }

    client_max_body_size 2048m;
    location /api/ {
        proxy_pass http://127.0.0.1:18080/api/;
        proxy_http_version 1.1;
        proxy_request_buffering off;
        proxy_read_timeout 7200s;
        proxy_send_timeout 7200s;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }

    location / {
        return 200 "oral-video-agent certificate bootstrap\n";
        add_header Content-Type text/plain;
    }
}
EOF

ln -sfn "$NGINX_SITE" /etc/nginx/sites-enabled/oral-video-cloud.conf
nginx -t
systemctl reload nginx

"$CERTBOT" certonly \
  --non-interactive \
  --agree-tos \
  --register-unsafely-without-email \
  --preferred-profile shortlived \
  --webroot \
  --webroot-path "$WEBROOT" \
  --ip-address "$PUBLIC_IP"

cat >"$NGINX_SITE" <<EOF
server {
    listen 80 default_server;
    listen [::]:80 default_server;
    server_name $PUBLIC_IP _;

    location ^~ /.well-known/acme-challenge/ {
        root $WEBROOT;
        default_type text/plain;
    }

    location / {
        return 308 https://$PUBLIC_IP\$request_uri;
    }
}

server {
    listen 443 ssl default_server;
    listen [::]:443 ssl default_server;
    server_name $PUBLIC_IP;

    ssl_certificate /etc/letsencrypt/live/$PUBLIC_IP/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/$PUBLIC_IP/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_session_cache shared:SSL:10m;
    ssl_session_timeout 1d;

    add_header Strict-Transport-Security "max-age=31536000" always;
    add_header X-Content-Type-Options "nosniff" always;

    client_max_body_size 2048m;
    send_timeout 7200s;

    location /api/ {
        proxy_pass http://127.0.0.1:18080/api/;
        proxy_http_version 1.1;
        proxy_request_buffering off;
        proxy_read_timeout 7200s;
        proxy_send_timeout 7200s;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
    }

    location ^~ /admin {
        proxy_pass http://127.0.0.1:18080;
        proxy_http_version 1.1;
        proxy_read_timeout 120s;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
    }

    location / {
        return 200 "oral-video-agent cloud api is running securely\n";
        add_header Content-Type text/plain;
    }
}
EOF

cat >/etc/systemd/system/oral-video-cert-renew.service <<EOF
[Unit]
Description=Renew the short-lived Let's Encrypt IP certificate
After=network-online.target nginx.service

[Service]
Type=oneshot
ExecStart=$CERTBOT renew --quiet --deploy-hook "systemctl reload nginx"
EOF

cat >/etc/systemd/system/oral-video-cert-renew.timer <<'EOF'
[Unit]
Description=Renew the oral-video-agent IP certificate twice daily

[Timer]
OnBootSec=5m
OnUnitActiveSec=12h
RandomizedDelaySec=30m
Persistent=true

[Install]
WantedBy=timers.target
EOF

nginx -t
systemctl reload nginx
systemctl daemon-reload
systemctl enable --now oral-video-cert-renew.timer
"$CERTBOT" certificates
