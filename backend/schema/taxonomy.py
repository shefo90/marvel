"""Browse-structure contracts: the navigation tree and the collections.

Zero logic — Pydantic models only.

``list_id`` appears on every one of these because section 5 ties the list a
shopper browsed to the cart line and then the order line. It is never localized:
the Arabic and English pages for the same category must report the same
``item_list_id``, or one shop's traffic splits into two in every report.
"""

from pydantic import BaseModel


class taxonomy_image(BaseModel):
    """Artwork for a tile.

    Width and height are optional here, unlike on a product image: an operator's
    own ``og_image_url`` is a bare URL with no dimensions recorded, while a
    borrowed product shot carries them. The frontend reserves space from the
    aspect ratio it lays out with, so a missing pair costs nothing in CLS.
    """

    url: str
    alt_text: str | None = None
    width: int | None = None
    height: int | None = None


class taxonomy_node(BaseModel):
    id: int
    slug: str
    title: str
    description: str | None = None
    list_id: str
    # The operator's own artwork if they set one, otherwise a photograph
    # borrowed from a product inside it, so a tile is never blank.
    image: taxonomy_image | None = None
    seo_title: str | None = None
    meta_description: str | None = None
    is_indexable: bool = True
    canonical_url: str | None = None


class category_node(taxonomy_node):
    level: int
    children: list["category_node"] = []


class category_detail(category_node):
    # For the breadcrumb. None on a level-1 category, which has no parent.
    parent: category_node | None = None


class collection_node(taxonomy_node):
    pass
