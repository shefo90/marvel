"""Collection <-> product membership.

``position`` is unique per collection so section 5's ``index`` parameter on
``view_item_list`` / ``select_item`` is deterministic rather than dependent on
query ordering.
"""

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import mapped_column, relationship

from core.db import Base


class CollectionProduct(Base):
    __tablename__ = "collection_products"

    collection_id = mapped_column(
        BigInteger,
        ForeignKey("collections.id", ondelete="CASCADE"),
        primary_key=True,
    )
    product_id = mapped_column(
        BigInteger, ForeignKey("products.id", ondelete="CASCADE"), primary_key=True
    )
    position = mapped_column(Integer, nullable=False, server_default="0")
    created_at = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    collection = relationship("Collection", back_populates="product_links")
    product = relationship("Product", back_populates="collection_links")

    __table_args__ = (
        UniqueConstraint(
            "collection_id", "position", name="uq_collection_products_position"
        ),
        CheckConstraint("position >= 0", name="ck_collection_products_position"),
        # "Which edits is this product in" — for the PDP and for select_item
        # attribution.
        Index("ix_collection_products_product_id", "product_id"),
    )
