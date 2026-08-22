# Restoring the shop

Do this once on a scratch machine before you need it. A backup nobody has
restored is a hypothesis, and the moment you find out it does not work is
always the worst possible moment.

You need **both** files from the same run:

- `marvel-db-<stamp>.dump` — orders, products, customers
- `marvel-media-<stamp>.tar.gz` — every product photograph

Restoring only the first gives you a shop whose every listing points at a
missing image.

---

## 1. Bring up the stack

```sh
cp .env.production.example .env.production   # fill in SECRET_KEY, POSTGRES_PASSWORD, PUBLIC_ORIGIN
docker compose -f docker-compose.prod.yml --env-file .env.production up -d db
```

Only the database. The API runs migrations on start, and letting it do that
against a database you are about to overwrite wastes time at best.

## 2. Restore the database

```sh
docker compose -f docker-compose.prod.yml --env-file .env.production \
  exec -T db pg_restore -U marvel -d marvel --clean --if-exists \
  < backups/marvel-db-<stamp>.dump
```

`--clean --if-exists` drops what it is about to replace, so this is safe to run
over an existing database. Expect it to be noisy — `pg_restore` reports errors
for objects that did not exist to drop. Those lines are normal.

## 3. Restore the photographs

```sh
docker run --rm \
  -v marvel_marvel_media:/data \
  -v "$PWD/backups:/backup:ro" \
  alpine sh -c "rm -rf /data/* && tar xzf /backup/marvel-media-<stamp>.tar.gz -C /data"
```

The volume name has the project prefix on it (`marvel_` from `name: marvel` in
the compose file, plus the volume's own `marvel_media`). `docker volume ls` if
in doubt.

## 4. Start everything

```sh
docker compose -f docker-compose.prod.yml --env-file .env.production up -d --build
```

The API runs `alembic upgrade head` on start, so a dump taken from an older
schema is migrated forward on the way up.

## 5. Check it actually worked

```sh
curl -fsS http://localhost/api/health
curl -fsS http://localhost/en | head -20
```

Then open the shop and load a product page. **Look at the photograph**, do not
just check the page renders — a missing media volume produces a page that is
structurally perfect and visually empty, which is precisely the failure this
step exists to catch.

Sign in to `/admin` and confirm the order list has the orders you expect.

---

## If the certificate does not come back

Caddy keeps issued certificates in the `marvel_caddy_data` volume. If that was
lost, it re-requests on start — which is fine unless you have been restarting
repeatedly, because Let's Encrypt rate-limits failures hard enough to take you
off TLS for a week.

If you are testing restores, set `SITE_DOMAIN=` empty so Caddy serves plain
HTTP and never touches Let's Encrypt at all.
