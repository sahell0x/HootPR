#!/bin/sh
# HootPR Postgres backups (runs inside the `backup` service of docker-compose.prod.yml).
#   backup.sh          loop: dump every day at BACKUP_HOUR_UTC, prune dumps older than BACKUP_KEEP_DAYS
#   backup.sh once     one dump now (`make backup`), then prune
# Connection comes from PGHOST / PGUSER / PGDATABASE / PGPASSWORD. Dumps: /backups/hootpr-<UTC>.dump (pg_dump -Fc).
set -eu

DIR=/backups
KEEP_DAYS="${BACKUP_KEEP_DAYS:-7}"
HOUR="${BACKUP_HOUR_UTC:-3}"

dump() {
  ts=$(date -u +%Y%m%dT%H%M%SZ)
  out="$DIR/hootpr-$ts.dump"
  echo "backup: dumping to $out"
  pg_dump -Fc --no-owner -f "$out.part" || { rm -f "$out.part"; return 1; }
  mv "$out.part" "$out" || return 1
  # -mtime +N matches files older than N+1 whole days: keep KEEP_DAYS days of dumps.
  find "$DIR" -name 'hootpr-*.dump' -mtime +"$((KEEP_DAYS - 1))" -print -delete
  find "$DIR" -name 'hootpr-*.dump.part' -mmin +120 -delete
  echo "backup: done ($(du -h "$out" | cut -f1))"
}

mkdir -p "$DIR"

if [ "${1:-}" = "once" ]; then
  dump
  exit 0
fi

echo "backup: nightly at ${HOUR}:00 UTC, keeping ${KEEP_DAYS} days"
while true; do
  now=$(date -u +%s)
  next=$(date -u -d "today ${HOUR}:00" +%s)
  if [ "$next" -le "$now" ]; then
    next=$(date -u -d "tomorrow ${HOUR}:00" +%s)
  fi
  sleep "$((next - now))"
  dump || echo "backup: FAILED" >&2
done
