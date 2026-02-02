#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

echo "Deploying Ethereum contract via Truffle..."
pushd contracts >/dev/null
npm install
OUT="$($(npm run migrate))"
popd >/dev/null

echo "$OUT"

ADDR="$(echo "$OUT" | grep -Eo 'DeliveryChain: 0x[a-fA-F0-9]{40}' | tail -n 1 | awk '{print $2}')"
if [ -z "${ADDR:-}" ]; then
  echo "Could not find contract address in output."
  echo "Paste it manually into .env as ETH_CONTRACT_ADDRESS."
  exit 1
fi

# Update ETH_CONTRACT_ADDRESS in .env
if grep -q '^ETH_CONTRACT_ADDRESS=' .env; then
  sed -i '' "s/^ETH_CONTRACT_ADDRESS=.*/ETH_CONTRACT_ADDRESS=$ADDR/" .env
else
  echo "ETH_CONTRACT_ADDRESS=$ADDR" >> .env
fi

echo "Set ETH_CONTRACT_ADDRESS=$ADDR in .env"
echo "Restarting backend..."
docker compose restart backend

echo "Done.
"