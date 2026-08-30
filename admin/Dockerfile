# The back-office: a static bundle behind a small file server.
#
# Unlike the storefront this has nothing to server-render. It is behind a login,
# no crawler will ever see it, and every screen fetches its own data. So it
# builds to files and something quiet serves them.

# --- build ------------------------------------------------------------------
FROM node:22-slim AS build

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY . .

# vite.config.js sets base: '/admin/', so every asset URL in the output is
# already prefixed. Serving this anywhere other than /admin/ 404s every chunk.
RUN npm run build

# --- runtime ----------------------------------------------------------------
FROM caddy:2-alpine AS runtime

# Caddy rather than nginx, matching the reverse proxy in front of it: one
# server to understand instead of two, and its config for this job is four
# lines.
COPY --from=build /app/dist /srv/admin

# try_files with a fallback to index.html is what makes a client-routed app
# survive a refresh: /admin/products/7 is a route React knows and the file
# system does not, so without this a reload on any screen but the first is a
# 404.
#
# The assets are content-hashed by Vite, so they are immutable and cached for a
# year; index.html is not, and must never be, or a deploy leaves browsers
# holding a page that points at chunks which no longer exist.
RUN printf '%s\n' \
    ':80 {' \
    '  root * /srv' \
    '  encode gzip zstd' \
    '  redir /admin /admin/ 308' \
    '  handle_path /admin/* {' \
    '    root * /srv/admin' \
    '    try_files {path} /index.html' \
    '    file_server' \
    '    header /assets/* Cache-Control "public, max-age=31536000, immutable"' \
    '    header /index.html Cache-Control "no-cache"' \
    '  }' \
    '  respond 404' \
    '}' > /etc/caddy/Caddyfile

EXPOSE 80

HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=5 \
    CMD wget -qO- http://localhost/admin/ >/dev/null 2>&1 || exit 1
