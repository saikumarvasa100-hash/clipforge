#!/bin/bash
# ClipForge -- One-command server setup
set -euo pipefail

DOMAIN="${1:-clipforge.example.com}"

echo "=== Installing system dependencies ==="
sudo apt-get update
sudo apt-get install -y apt-transport-https ca-certificates curl software-properties-common nginx certbot python3-certbot-nginx

# Docker
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER

echo "=== Setting up ClipForge ==="
cd /opt
sudo git clone https://github.com/yourorg/clipforge.git || true
cd /opt/clipforge
cp backend/.env.example .env
# Edit .env with your keys

echo "=== Starting services ==="
sudo docker compose up -d

echo "=== Running migrations ==="
sudo docker compose run --rm backend alembic upgrade head

echo "=== Configuring HTTPS ==="
sudo certbot --nginx -d "$DOMAIN" --non-interactive --agree-tos --email admin@"$DOMAIN"

echo ""
echo "============================================="
echo "  ClipForge is live at https://${DOMAIN}"
echo "============================================="
