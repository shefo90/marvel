"""App creation and router registration, nothing more."""

import os

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from core.config import MEDIA_ROOT, MEDIA_URL_PREFIX
from core.db import Engine
from routes import (
    account,
    admin_catalog,
    admin_images,
    admin_orders,
    admin_promotions,
    admin_taxonomy,
    auth,
    cart,
    order,
    product,
    refresh,
    register,
    seo,
)
from services import cache


class NoSniffStaticFiles(StaticFiles):
    """Uploaded files, served with sniffing disabled.

    Everything under here was decoded and re-encoded before it was stored, so it
    really is the image type its extension claims. ``nosniff`` closes the
    remaining gap: without it a browser is free to disagree with our
    Content-Type and execute what it decides the bytes are, from our own origin.
    """

    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

app = FastAPI(
    title="Marvel Commerce API",
    description=(
        "S1 commerce core. Egypt / EGP, English + Arabic. "
        "See docs/superpowers/specs/2026-08-16-s1-commerce-core-design.md"
    ),
    version="0.1.0",
)

# Registered before the locale-scoped routers so "/api/admin/..." is matched as
# a literal path and never offered to "/api/{locale}/..." as locale="admin".
app.include_router(admin_catalog.router)
app.include_router(admin_images.router)
app.include_router(admin_promotions.router)
app.include_router(admin_orders.router)
app.include_router(admin_taxonomy.router)

# Uploaded imagery. Created on startup because StaticFiles refuses to mount a
# directory that does not exist, and a fresh checkout has never uploaded
# anything.
os.makedirs(MEDIA_ROOT, exist_ok=True)
app.mount(MEDIA_URL_PREFIX, NoSniffStaticFiles(directory=MEDIA_ROOT), name="media")

app.include_router(product.router)
app.include_router(register.router)
app.include_router(auth.router)
app.include_router(refresh.router)
app.include_router(account.router)
app.include_router(cart.router)
app.include_router(order.router)

# Root-level and crawler-facing: /robots.txt, /sitemap.xml, /sitemap-{locale}.xml.
# Registered last so its bare paths cannot shadow an /api route.
app.include_router(seo.router)


@app.get("/health", tags=["ops"])
def health():
    """Liveness plus dependency status.

    Redis being down is reported, not fatal: the cache degrades to a miss and
    the storefront keeps serving from Postgres. Postgres being down is fatal.
    """
    try:
        with Engine.connect() as conn:
            conn.execute(text("select 1"))
        db_ok = True
    except Exception:  # noqa: BLE001
        db_ok = False

    return {
        "status": "ok" if db_ok else "degraded",
        "database": "up" if db_ok else "down",
        "cache": "up" if cache.ping() else "down",
    }
