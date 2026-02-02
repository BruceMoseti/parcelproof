#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

if [ ! -f ".env" ]; then
  cp .env.example .env
  echo "Created .env from .env.example"
fi

echo "Starting Docker stack..."
docker compose up -d --build

echo "Waiting for backend to be reachable..."
for i in {1..60}; do
  if curl -fsS "http://localhost:8080/api/health" >/dev/null; then
    echo "Backend is up."
    break
  fi
  sleep 1
done

echo ""
echo "Stack running:"
echo "  Website: http://localhost:5173"
echo "  Admin Integrations: http://localhost:5173/admin/integrations"
echo "  Backend: http://localhost:8080/api/health"
echo "  IPFS Gateway: http://localhost:8081"