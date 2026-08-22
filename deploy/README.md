# Deploying to a VPS

The whole shop in seven containers behind one proxy. **One `docker-compose.yml`
for development and production** -- the difference between them is `.env`, not a
second compose file. Everything is reachable at
a single origin, because that is what the applications assume: the admin calls
`/api/...` relative, the shopper's session cookie is scoped to `/api` on the
same host, and the API has no CORS middleware to make a split origin work.

| Path | Served by |
|---|---|
| `/` | storefront (server-rendered) |
| `/admin/*` | admin bundle |
| `/api/*` | API |
| `/media/*` | API — uploaded photographs |
| `/robots.txt`, `/sitemap*.xml` | API |

Caddy is the only service bound to every interface. Postgres, Redis and the API
publish to `127.0.0.1` only -- reachable from the server itself for psql, curl
and the test suite, and from the internet not at all. The storefront and the
back-office publish nothing, which also leaves ports 3000 and 5173 free for
`npm run dev`.

---

## First deployment

```sh
git clone <repo> /srv/marvel && cd /srv/marvel

cp .env.example .env
# Fill in SECRET_KEY, POSTGRES_PASSWORD, PUBLIC_ORIGIN and COOKIE_SECURE=1.
# The file tells you how to generate the two secrets. Leave SITE_DOMAIN empty
# until DNS resolves.
#
# Locally you can skip this entirely: docker-compose.yml carries a development
# default for every one of them. Those defaults are public, which is precisely
# why a deployment cannot use them.

docker compose up -d --build
```

The API runs `alembic upgrade head` on start, so the schema is created and
migrated on the way up. Migration `0008` inserts the two locale rows — without
them every catalogue route answers 404 while `/health` still reports OK, which
is a confusing enough failure that it is in a migration rather than a script.

Check it:

```sh
curl -fsS http://<server-ip>/api/health     # {"status":"ok","database":"up","cache":"up"}
curl -fsS http://<server-ip>/en | head
```

A brand-new shop has no products. Either add them through `/admin`, or seed the
demo catalogue to see the thing working:

```sh
docker compose \
  exec api sh -c "python scripts/seed_taxonomy.py && python scripts/seed_demo_catalogue.py"
```

Create the first staff login:

```sh
docker compose \
  exec api python scripts/bootstrap_admin.py
```

## Turning on HTTPS

Point an A record at the server, wait for it to resolve, then:

```sh
# in .env
SITE_DOMAIN=marvelshop.example
PUBLIC_ORIGIN=https://marvelshop.example

docker compose up -d
```

Caddy obtains the certificate on start and renews it on its own — no certbot, no
cron, no reload hook. **Both variables change together**: `SITE_DOMAIN` is what
gets a certificate, `PUBLIC_ORIGIN` is what the pages print in canonical tags,
hreflang and the sitemap. Changing only the first serves HTTPS pages that tell
Google the real ones live on an IP address.

Do not set `SITE_DOMAIN` before DNS resolves. Let's Encrypt validates by
connecting to the name, and repeated failures burn a rate limit that can block
issuance for a week.

## Updating

```sh
git pull
docker compose up -d --build
```

Migrations run automatically. Rebuilt containers replace running ones one at a
time; there is a few seconds of downtime, which is the honest trade for a
single-VPS setup with no load balancer.

## Backups

```sh
./deploy/backup.sh /mnt/backups
```

Two files, and you need both — a database dump contains no product photographs.
See [RESTORE.md](RESTORE.md), and run the restore once on a scratch box before
you are relying on it.

From cron:

```
15 3 * * *  cd /srv/marvel && ./deploy/backup.sh /mnt/backups >> /var/log/marvel-backup.log 2>&1
```

Copy the files off the machine. A backup on the same disk as the thing it backs
up is not a backup.

## Things worth knowing

**Set `COOKIE_SECURE=1` in `.env` for production.** Left empty, the API decides
from the request scheme, which is already correct behind Caddy with
`--proxy-headers` — so this is belt and braces rather than the only thing
holding the cookie's `Secure` flag on. It also arms the SECRET_KEY check below,
which is the real reason not to skip it.

**The API refuses to start** if `SECRET_KEY` is missing or still the development
value while `COOKIE_SECURE` is on. That check exists because the development key
is in a tracked file, and anything signed with it can be forged — including an
admin token.

**`marvel_media` is the only application state outside Postgres.** Every product
photograph is in it. `docker compose down -v` deletes it along with the
database.

**Redis is a cache and only a cache.** It runs with `allkeys-lru` and a 256 MB
cap, so it evicts rather than refusing writes. Losing it costs a slow minute,
not data — the background queue is a Postgres table, deliberately, so that jobs
commit with the rows that caused them.

## What has not been tested

The stack was built and run end to end locally: all seven containers healthy,
every route above returning 200, images served, sitemap and robots reachable,
server-rendered pages carrying absolute canonicals and hreflang.

**It has not been run on a real VPS, and TLS has never been exercised** — that
needs a domain and a public IP. The HTTPS path is one variable away and Caddy's
behaviour here is well-trodden, but treat the first deployment as the test it
is, and check `docker compose logs caddy` if the certificate does not appear.
