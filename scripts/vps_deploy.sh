#!/usr/bin/env bash
set -euo pipefail

# Deploy CustomRMM on a VPS using Docker Compose.
# Usage:
#   bash scripts/vps_deploy.sh

if [[ ! -f ".env" ]]; then
  echo "Missing .env. Copy .env.example to .env and set SECRET_KEY first."
  exit 1
fi

mkdir -p data
docker compose up -d --build
echo "CustomRMM is running. Visit: ${BASE_URL:-http://localhost:8000}/setup-admin"
