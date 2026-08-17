"""App creation and router registration, nothing more."""

from fastapi import FastAPI
from sqlalchemy import text

from core.db import Engine
from routes import admin_catalog, auth, cart, order, product, refresh, register
from services import cache

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

app.include_router(product.router)
app.include_router(register.router)
app.include_router(auth.router)
app.include_router(refresh.router)
app.include_router(cart.router)
app.include_router(order.router)


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
