"""Admin catalog contracts. No logic here — see repositories/admin_catalog.py."""

from pydantic import BaseModel


class translation_state(BaseModel):
    """Per-locale publish state, so the operator can see what is unfinished."""

    locale: str
    is_published: bool
    is_complete: bool


class admin_product_row(BaseModel):
    id: int
    slug: str
    title: str
    brand: str
    status: str
    variant_count: int
    image_count: int
    translations: list[translation_state]


class admin_product_list_response(BaseModel):
    items: list[admin_product_row]
    page: int
    page_size: int
    total: int
