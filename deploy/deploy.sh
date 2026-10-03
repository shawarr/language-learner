#!/usr/bin/env bash
# Build and (re)start the app. Run as root on the server from the repo root.
set -euo pipefail

cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

[ -f .env ] || { echo "missing .env (cp .env.example .env and fill it in)" >&2; exit 1; }

mkdir -p data/audio
# The container runs as uid 1000. A root-owned data dir makes every write fail with
# "attempt to write a readonly database" while reads keep working — silently.
chown -R 1000:1000 data

docker compose build
docker compose up -d

printf 'waiting for health'
for _ in $(seq 1 30); do
  if curl -fsS http://127.0.0.1:9003/api/health >/dev/null 2>&1; then
    echo " -> ok"
    docker compose ps
    exit 0
  fi
  printf '.'
  sleep 2
done

echo " -> FAILED" >&2
docker compose logs --tail 50 >&2
exit 1
