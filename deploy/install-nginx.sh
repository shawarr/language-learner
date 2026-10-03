#!/usr/bin/env bash
# Installs the nginx vhost, snippets and rate-limit zones, then reloads nginx.
# Run as root on the server, from the repo root. Idempotent.
set -euo pipefail

DOMAIN="${DOMAIN:-german.shawar.xyz}"
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

install -m 644 "$REPO/deploy/snippets/tutor-proxy.conf"            /etc/nginx/snippets/
install -m 644 "$REPO/deploy/snippets/tutor-security-headers.conf" /etc/nginx/snippets/
install -m 644 "$REPO/deploy/ratelimit.conf"                       /etc/nginx/conf.d/tutor-ratelimit.conf

# Keep an existing vhost if certbot has already edited it in place.
if [ -f "/etc/nginx/sites-available/$DOMAIN" ] && grep -q "managed by Certbot" "/etc/nginx/sites-available/$DOMAIN"; then
  echo "vhost already exists and is certbot-managed; leaving it alone"
else
  sed "s/german\.shawar\.xyz/$DOMAIN/g" "$REPO/deploy/nginx.conf" > "/etc/nginx/sites-available/$DOMAIN"
  ln -sfn "/etc/nginx/sites-available/$DOMAIN" "/etc/nginx/sites-enabled/$DOMAIN"
fi

nginx -t
systemctl reload nginx
echo "nginx configured for $DOMAIN"
echo "TLS:  certbot --nginx -d $DOMAIN"
