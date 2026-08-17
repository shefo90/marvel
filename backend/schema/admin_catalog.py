"""Admin catalog contracts. No logic here — see repositories/admin_catalog.py."""

from pydantic import BaseModel, Field


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


class admin_product_create(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    slug: str = Field(min_length=1, max_length=255)
    brand: str = Field(default="Pixi", max_length=128)
    category_id: int
    description: str | None = None
    tags: list[str] = []
    condition: str = "new"
    gender: str | None = None
    age_group: str | None = None
    item_group_id: str | None = None


class admin_product_detail(BaseModel):
    id: int
    item_group_id: str
    slug: str
    title: str
    brand: str
    status: str
    category_id: int
