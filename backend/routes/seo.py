"""Crawler-facing endpoints, served from the site root rather than under /api.

They live in the API because they need the database, and they are reachable at
the storefront's origin because a sitemap at a different origin is ignored and a
robots.txt at a different origin governs nothing. The reverse proxy maps these
three paths here; everything else at the root goes to the storefront renderer.

No SQLAlchemy in this layer.
"""

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from core.db import get_db
from repositories.sitemap import robots_txt, sitemap_for_locale, sitemap_index
from routes.product import valid_locale

router = APIRouter(tags=["seo"])

# Crawlers re-fetch these often and the content changes only when the catalogue
# does. An hour is short enough to pick up a publish and long enough that a
# crawl does not become a load test.
_CACHE = "public, max-age=3600"


@router.get("/robots.txt", response_class=Response)
def robots():
    return Response(content=robots_txt(), media_type="text/plain", headers={"Cache-Control": _CACHE})


@router.get("/sitemap.xml", response_class=Response)
def sitemap_root(db: Session = Depends(get_db)):
    """The index. One sitemap per active language, because the two publish
    independently and an Arabic push should not restate English freshness."""
    return Response(
        content=sitemap_index(db),
        media_type="application/xml",
        headers={"Cache-Control": _CACHE},
    )


@router.get("/sitemap-{locale}.xml", response_class=Response)
def sitemap_locale(locale: str = Depends(valid_locale), db: Session = Depends(get_db)):
    """One language. An unknown locale 404s rather than returning an empty
    urlset — a soft 404 is exactly what section 8A forbids."""
    return Response(
        content=sitemap_for_locale(db, locale),
        media_type="application/xml",
        headers={"Cache-Control": _CACHE},
    )
