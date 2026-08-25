"""Search — a thin front on the listing query.

Deliberately not its own query. Search results are a product listing: they need
the same card payload, the same facets, the same sorting and the same
visibility rules as a category page, and a second implementation of all of that
is a second place for them to diverge. What search adds is one predicate and
one rule about the empty string.

The folding that makes Arabic work lives in the database (migration 0007) and is
applied on both sides -- to the stored text at write time by a generated column,
and to the query here by the same ``marvel_fold`` function. Search's one
unsurvivable bug is those two disagreeing, so there is exactly one definition.

**Known limitation: Arabic broken plurals do not match their singulars.**
Measured against the real catalogue, a shopper searching ``أحذية`` ("shoes")
finds none of the products titled ``حذاء`` ("shoe"). This is not a folding
failure -- both spellings of the plural fold identically, and that was verified
-- it is morphology. Arabic forms many plurals by reshaping the word rather than
suffixing it, and the snowball stemmer reduces ``حذاء`` to ``حذاء`` but ``أحذية``
to ``احذ``. The two never meet. The fuzzy clauses cannot rescue it either: the
pair scores 0.167 on word_similarity, and dropping the threshold that far would
match almost anything.

Fixing it needs lemma knowledge -- a curated synonym table mapping the shop's
own vocabulary (حذاء/أحذية, صندل/صنادل, حقيبة/حقائب), which is small because a
shoe shop's vocabulary is small, or a full Arabic lemmatizer, which is not.
Deliberately not built here: it is a different feature from folding, and which
words matter is the shop owner's knowledge rather than a developer's guess.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from repositories.product import list_products

# Long enough to be a word, short enough for "38". A single character matches a
# large fraction of the catalogue through the trigram clause and tells the
# shopper nothing.
MIN_QUERY = 2


def search_products(db: Session, locale: str, q: str | None, **kwargs) -> dict:
    """Search, returning the same shape as a listing plus the query itself.

    An empty or one-character query returns nothing rather than everything. A
    blank search that answers with the whole catalogue reads as a broken filter,
    and on a catalogue larger than this one it is an accidental full scan
    triggered by a stray keystroke.
    """
    query = (q or "").strip()

    if len(query) < MIN_QUERY:
        return {
            "items": [],
            "total": 0,
            "page": 1,
            "page_size": kwargs.get("page_size", 24),
            "item_list_id": "search",
            "item_list_name": "Search results",
            "sort": kwargs.get("sort", "featured"),
            "facets": {"sizes": [], "colors": [], "price": {"min": None, "max": None}},
            "query": query,
        }

    results = list_products(db, locale, q=query, **kwargs)

    # Section 5 wants one list identity for search, distinct from any category,
    # so impressions from a search can be told apart from browse impressions.
    results["item_list_id"] = "search"
    results["item_list_name"] = "Search results"
    results["query"] = query
    return results
