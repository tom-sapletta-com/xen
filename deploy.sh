#!/bin/bash
# xen — deploy na VPS z TLS
# Użycie: ./deploy.sh twoja-domena.pl

set -euo pipefail

DOMAIN="${1:?Użycie: ./deploy.sh twoja-domena.pl}"

echo "🚀 xen deploy → ${DOMAIN}"

# 1. Prereqs
echo "📦 Instalacja zależności..."
apt-get update -qq
apt-get install -y -qq docker.io docker-compose certbot > /dev/null

# 2. TLS cert
echo "🔐 Generowanie certyfikatu TLS..."
if [ ! -f "certs/fullchain.pem" ]; then
    certbot certonly --standalone \
        -d "${DOMAIN}" \
        --non-interactive \
        --agree-tos \
        --email "admin@${DOMAIN}" \
        || {
            echo "⚠️  Certbot nie zadziałał — generuję self-signed cert..."
            mkdir -p certs
            openssl req -x509 -nodes -days 365 \
                -newkey rsa:2048 \
                -keyout certs/privkey.pem \
                -out certs/fullchain.pem \
                -subj "/CN=${DOMAIN}"
        }

    # Link certbot certs
    if [ -f "/etc/letsencrypt/live/${DOMAIN}/fullchain.pem" ]; then
        mkdir -p certs
        cp "/etc/letsencrypt/live/${DOMAIN}/fullchain.pem" certs/
        cp "/etc/letsencrypt/live/${DOMAIN}/privkey.pem" certs/
    fi
fi

# 3. Update nginx config z domeną
sed -i "s/server_name _;/server_name ${DOMAIN};/g" nginx/nginx.conf

# 4. Build & run
echo "🐳 Budowanie kontenerów..."
docker-compose build --quiet
docker-compose up -d

echo ""
echo "✅ xen działa!"
echo "   https://${DOMAIN}"
echo ""
echo "   Logi:    docker-compose logs -f"
echo "   Stop:    docker-compose down"
echo "   Restart: docker-compose restart"

# 5. Auto-renewal cron
if command -v certbot &> /dev/null; then
    (crontab -l 2>/dev/null; echo "0 3 * * * certbot renew --quiet && cp /etc/letsencrypt/live/${DOMAIN}/*.pem $(pwd)/certs/ && docker-compose restart nginx") | crontab -
    echo "   Auto-renewal: skonfigurowany (cron)"
fi
