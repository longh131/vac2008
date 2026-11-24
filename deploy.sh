#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

if [[ ! -f .env ]]; then
  echo "Missing .env. Copy .env.example and edit it." >&2
  exit 1
fi

if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  git pull --ff-only
fi

docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build --force-recreate web

for _ in $(seq 1 30); do
  if docker exec vac2008_web curl -fsS http://localhost:8000/health >/dev/null; then
    echo "vac2008_web is up."
    echo "Cron (America/Chicago):"
    echo "CRON_TZ=America/Chicago"
    echo "30 5 * * * docker exec vac2008_web python -m jobs.crawl >> /opt/vac2008/logs/crawl.log 2>&1"
    echo "0 7 * * * docker exec vac2008_web python -m jobs.digest >> /opt/vac2008/logs/digest.log 2>&1"
    exit 0
  fi
  sleep 2
done

echo "vac2008_web did not become healthy" >&2
exit 1
