# The shop: Express + Vike, server-rendered.
#
# Not a static bundle. The catalogue has to arrive rendered in the first
# response -- a crawler that receives an empty div gets no title, no price and
# no structured data -- so this ships a Node process, not a folder of files.

# --- build ------------------------------------------------------------------
FROM node:22-slim AS build

WORKDIR /app

# npm ci, not npm install: it installs exactly the lockfile and fails if the two
# disagree, which is the difference between a reproducible image and one that
# quietly picked up a new minor version on a Tuesday.
COPY package.json package-lock.json ./
RUN npm ci

COPY . .
RUN npm run build

# --- runtime ----------------------------------------------------------------
FROM node:22-slim AS runtime

ENV NODE_ENV=production \
    PORT=3000

WORKDIR /app

# Production dependencies only. The build stage needed vite and the test
# runner; the running server needs express, compression and vike.
COPY package.json package-lock.json ./
RUN npm ci --omit=dev && npm cache clean --force

# server.js reads NODE_ENV and serves dist/client when it is "production",
# taking the Vite dev-middleware path otherwise. Both halves of the build are
# needed: dist/client for assets, dist/server for the render.
COPY --from=build /app/dist ./dist
COPY server.js ./
COPY pages ./pages
COPY components ./components
COPY layouts ./layouts
COPY hooks ./hooks
COPY services ./services
COPY utils ./utils
COPY assets ./assets

# The node image ships an unprivileged `node` user. Nothing here writes to
# disk, so it only needs to read what was copied in.
USER node
EXPOSE 3000

# No curl in this image, and no reason to add one: Node can make the request
# itself, which keeps the layer smaller and the surface narrower.
HEALTHCHECK --interval=10s --timeout=3s --start-period=20s --retries=5 \
    CMD node -e "fetch('http://localhost:3000/en').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"

CMD ["node", "server.js"]
