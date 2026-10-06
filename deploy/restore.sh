#!/usr/bin/env bash
# Restore a HootPR Postgres backup into the running production stack.
#   deploy/restore.sh                      list dumps in the `backups` volume
#   deploy/restore.sh hootpr-<ts>.dump     restore a dump from the volume
#   deploy/restore.sh ./path/to/file.dump  copy a host file into the volume, then restore it
# api + worker are stopped during the restore (no writes), then started again.
set -euo pipefail
cd "$(dirname "$0")/.."

compose() { docker compose -f docker-compose.yml -f docker-compose.prod.yml "$@"; }

if [[ $# -eq 0 ]]; then
  echo "Available backups:"
  compose exec -T backup sh -c 'ls -lh /backups/*.dump 2>/dev/null || echo "  (none)"'
  echo "Usage: $0 <file.dump>"
  exit 0
fi

src="$1"
if [[ -f "$src" ]]; then
  name="$(basename "$src")"
  compose cp "$src" "backup:/backups/$name"
else
  name="$src"
fi

compose exec -T backup test -f "/backups/$name" || { echo "no such backup: $name" >&2; exit 1; }

read -r -p "Restore $name over the current database? This overwrites live data. [y/N] " ok
[[ "$ok" == [yY] ]] || { echo "aborted"; exit 1; }

echo "Taking a safety dump first..."
compose exec -T backup sh /backup/backup.sh once

compose stop api worker
compose exec -T backup pg_restore --clean --if-exists --no-owner -d hootpr "/backups/$name"
compose up -d api worker
echo "Restored $name."
