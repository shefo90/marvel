#!/bin/sh
# Back up everything that cannot be rebuilt from git.
#
#     ./deploy/backup.sh                 # writes to ./backups
#     ./deploy/backup.sh /mnt/backups    # or wherever
#
# Run it from cron on the VPS:
#     15 3 * * *  cd /srv/marvel && ./deploy/backup.sh /mnt/backups >> /var/log/marvel-backup.log 2>&1
#
# **Two things, not one.** A pg_dump is the obvious half and only half the
# answer: uploaded product photographs live in the `marvel_media` volume and
# appear in no database dump. Restore a dump alone and the shop comes back with
# every listing pointing at an image that is not there. The media volume is the
# only application state outside Postgres, which is exactly why it is easy to
# forget.
#
# A backup nobody has restored is a hypothesis. deploy/RESTORE.md is the
# procedure; run it once against a scratch machine before you need it.

set -eu

DEST="${1:-./backups}"
STAMP="$(date +%Y%m%d-%H%M%S)"
COMPOSE="docker compose -f docker-compose.prod.yml --env-file .env.production"
KEEP_DAYS="${KEEP_DAYS:-14}"

mkdir -p "$DEST"

echo "==> database"
# --clean --if-exists so the dump can be replayed over an existing database
# without hand-dropping it first. Custom format (-Fc) because it restores
# selectively and compresses, which plain SQL does not.
$COMPOSE exec -T db pg_dump \
    -U "${POSTGRES_USER:-marvel}" \
    -d "${POSTGRES_DB:-marvel}" \
    --clean --if-exists -Fc \
    > "$DEST/marvel-db-$STAMP.dump"

echo "==> uploaded media"
# Read out of the volume through a throwaway container rather than from the
# API container, so this still works when the stack is down -- which is when
# you are most likely to want a backup.
docker run --rm \
    -v marvel_marvel_media:/data:ro \
    -v "$(cd "$DEST" && pwd):/backup" \
    alpine tar czf "/backup/marvel-media-$STAMP.tar.gz" -C /data .

echo "==> pruning backups older than $KEEP_DAYS days"
find "$DEST" -name 'marvel-db-*.dump' -mtime "+$KEEP_DAYS" -delete
find "$DEST" -name 'marvel-media-*.tar.gz' -mtime "+$KEEP_DAYS" -delete

echo
echo "wrote:"
ls -lh "$DEST/marvel-db-$STAMP.dump" "$DEST/marvel-media-$STAMP.tar.gz"
echo
echo "Both files are needed to restore. Copy them OFF this machine -- a backup"
echo "on the same disk as the thing it backs up is not a backup."
