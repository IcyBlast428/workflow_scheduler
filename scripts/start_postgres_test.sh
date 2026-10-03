#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd -P)"
cd "$ROOT"
name=wfs-postgres18-test
if docker container inspect "$name" >/dev/null 2>&1; then
  [[ "$(docker inspect --format '{{index .Config.Labels "wfs.project"}}' "$name")" == workflow_scheduler ]] || { echo 'Container name already belongs to another project.' >&2; exit 1; }
  [[ "$(docker inspect --format '{{.Config.Image}}' "$name")" == postgres:18.1 ]] || { echo 'Unexpected database image.' >&2; exit 1; }
  docker start "$name" >/dev/null
else
  docker run --pull=never --detach --name "$name" --label wfs.project=workflow_scheduler \
    --restart unless-stopped --publish 127.0.0.1:15432:5432 \
    --env-file .wfs-secrets/postgres-container.env \
    --mount type=volume,source=wfs-postgres18-test-data,target=/var/lib/postgresql \
    --shm-size=256m --memory=2g postgres:18.1 \
    -c timezone=Asia/Shanghai -c shared_buffers=256MB -c log_min_duration_statement=1000 >/dev/null
fi
for attempt in {1..30}; do
  if docker exec "$name" pg_isready -U wfstest -d wfstest >/dev/null; then
    echo 'PostgreSQL test database ready: 127.0.0.1:15432/wfstest'
    exit 0
  fi
  sleep 1
done
echo 'PostgreSQL test database did not become ready.' >&2
exit 1
