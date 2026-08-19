"""Back-office contracts for the category tree and the collections.

Zero logic — Pydantic models only.

``level`` is absent from every create payload deliberately. It is derived from
``parent_id`` in the repository, because ``categories.parent_level`` is a
generated column backing a composite foreign key: accepting a level from the
caller only creates a way for it to disagree with the parent.
"""

from pydantic import BaseModel, ConfigDict, Field


class admin_taxonomy_translation(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    locale: str
    title: str
    slug: str
    description: str | None = None
    meta_description: str | None = None
    is_published: bool = False


class admin_translation_upsert(BaseModel):
    title: str | None = None
    slug: str | None = None
    description: str | None = None
    seo_title: str | None = None
    meta_description: str | None = None
    is_published: bool | None = None


class admin_category_create(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    # None makes this a top-level category; a level-1 id makes it a child.
    parent_id: int | None = None
    slug: str | None = None
    list_id: str | None = None
    description: str | None = None
    google_product_category: str | None = None
    position: int | None = None
    is_active: bool = True


class admin_category_update(BaseModel):
    name: str | None = None
    slug: str | None = None
    list_id: str | None = None
    description: str | None = None
    google_product_category: str | None = None
    position: int | None = None
    is_active: bool | None = None


class admin_category_node(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    parent_id: int | None = None
    level: int
    name: str
    slug: str
    list_id: str
    position: int
    is_active: bool
    # Shown so the operator can see what deactivating this would hide.
    product_count: int = 0
    translations: list[admin_taxonomy_translation] = []
    children: list["admin_category_node"] = []


class admin_collection_create(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    slug: str | None = None
    list_id: str | None = None
    description: str | None = None
    position: int | None = None
    is_active: bool = True


class admin_collection_update(BaseModel):
    name: str | None = None
    slug: str | None = None
    list_id: str | None = None
    description: str | None = None
    position: int | None = None
    is_active: bool | None = None


class admin_collection_row(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    slug: str
    list_id: str
    description: str | None = None
    position: int
    is_active: bool
    product_count: int = 0
    translations: list[admin_taxonomy_translation] = []


class admin_collection_members(BaseModel):
    """The full membership, in order.

    Full rather than incremental because the order is the data: ``position``
    drives section 5's ``index`` and the collection's own "featured" sort, and
    an add/remove pair cannot express a reordering.
    """

    product_ids: list[int] = []
