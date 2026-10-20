#!/usr/bin/env bash
# Writes ./.env with FRESH random secrets (nothing printed). The model key is NOT here: it lives in keys.env.
set -euo pipefail
cd /home/ec2-user/ttf
[ -f .env ] && { echo ".env already exists: leaving it alone"; exit 0; }
umask 177
rnd() { openssl rand -hex 24; }
{
  echo "POSTGRES_USER=ttf"
  echo "POSTGRES_DB=ttf"
  echo "POSTGRES_PASSWORD=$(rnd)"
  echo "SECRET_KEY=$(rnd)$(rnd)"
  echo "FORGE_INTEGRATIONS_SECRET=$(rnd)"
  echo "APP_ENV=staging"
  echo "ALLOWED_ORIGINS=http://localhost:3100,http://127.0.0.1:3100"
  # the address builders' computers reach this server on (for the Watch live tunnel); set it to the public IP or name
  echo "PUBLIC_HOST=${PUBLIC_HOST:-}"
  echo "TUNNEL_SSH_PORT=2222"
} > .env
chmod 600 .env
echo ".env written ($(wc -l < .env) settings, secrets not shown)"
