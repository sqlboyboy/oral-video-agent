#!/usr/bin/env bash
set -euo pipefail

PUBLIC_IP="${1:?Usage: enable_ip_https_standard_443.sh <public-ip>}"
CERT_DIR="/etc/letsencrypt/live/$PUBLIC_IP"
WEBROOT=/var/www/certbot
NGINX_SITE=/etc/nginx/sites-available/oral-video-cloud.conf

if [[ ! -s "$CERT_DIR/fullchain.pem" || ! -s "$CERT_DIR/privkey.pem" ]]; then
  echo "The trusted IP certificate has not been issued" >&2
  exit 3
fi

rm -f /etc/nginx/stream-conf.d/oral-video-cloud-port80.conf
install -d -m 0755 "$WEBROOT/.well-known/acme-challenge"

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

    ssl_certificate $CERT_DIR/fullchain.pem;
    ssl_certificate_key $CERT_DIR/privkey.pem;
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

ln -sfn "$NGINX_SITE" /etc/nginx/sites-enabled/oral-video-cloud.conf
nginx -t
systemctl reload nginx
