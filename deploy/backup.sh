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

# Git Bash on Windows rewrites arguments that look like absolute paths, so
# "/backup/x.tar.gz" meant for the container becomes "C:/Program Files/Git/...".
# Harmless everywhere else; without it this script cannot be tested on the
# machine most likely to be running it during development.
export MSYS_NO_PATHCONV=1

DEST="${1:-./backups}"
STAMP="$(date +%Y%m%d-%H%M%S)"
COMPOSE="docker compose"

# Compose prefixes volume names with the project, which defaults to the
# directory name. Derived rather than hardcoded because the first version of
# this script guessed "marvel_marvel_media" while the real volume was
# "marvel_website_marvel_media" -- and `docker run -v` CREATES a volume that
# does not exist rather than failing, so it produced a valid, perfectly empty
# archive every night. A backup that looks fine and contains nothing is worse
# than no backup at all.
PROJECT="${COMPOSE_PROJECT_NAME:-$(basename "$(pwd)")}"
MEDIA_VOLUME="${PROJECT}_marvel_media"
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

echo "==> uploaded media  (volume: $MEDIA_VOLUME)"

# Refuse to back up a volume that does not exist, rather than letting docker
# helpfully create an empty one. See the note on MEDIA_VOLUME above.
if ! docker volume inspect "$MEDIA_VOLUME" >/dev/null 2>&1; then
    echo "  ERROR: no such volume: $MEDIA_VOLUME" >&2
    docker volume ls --format '    {{.Name}}' | grep marvel >&2 || true
    echo "  Set COMPOSE_PROJECT_NAME if this project runs under another name." >&2
    exit 1
fi
# Read out of the volume through a throwaway container rather than from the
# API container, so this still works when the stack is down -- which is when
# you are most likely to want a backup.
docker run --rm \
    -v "$MEDIA_VOLUME":/data:ro \
    -v "$(cd "$DEST" && pwd):/backup" \
    alpine tar czf "/backup/marvel-media-$STAMP.tar.gz" -C /data .

# An archive of an empty volume is about 45 bytes, which is the exact shape
# this script used to produce silently. Loud is better.
MEDIA_BYTES=$(wc -c < "$DEST/marvel-media-$STAMP.tar.gz")
if [ "$MEDIA_BYTES" -lt 200 ]; then
    echo "  WARNING: media archive is ${MEDIA_BYTES} bytes -- almost certainly empty." >&2
    echo "  If this shop has photographs, something is wrong:" >&2
    echo "    docker run --rm -v $MEDIA_VOLUME:/data alpine ls -R /data | head" >&2
fi

echo "==> pruning backups older than $KEEP_DAYS days"
find "$DEST" -name 'marvel-db-*.dump' -mtime "+$KEEP_DAYS" -delete
find "$DEST" -name 'marvel-media-*.tar.gz' -mtime "+$KEEP_DAYS" -delete

echo
echo "wrote:"
ls -lh "$DEST/marvel-db-$STAMP.dump" "$DEST/marvel-media-$STAMP.tar.gz"
echo
echo "Both files are needed to restore. Copy them OFF this machine -- a backup"
echo "on the same disk as the thing it backs up is not a backup."
