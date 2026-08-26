/**
 * GA4 ecommerce event payloads, built from what the API already returns.
 *
 * Two rules run through all of it.
 *
 * **``item_id`` is the SKU.** Section 2 makes the SKU the sellable identifier
 * and says explicitly that it is the same value GA4 and Ads use. Sending a
 * database id, or the product slug, would silently break every join between
 * analytics, Merchant Center and the Meta catalogue.
 *
 * **Raw numbers only.** Section 6.6: formatted numerals must never reach
 * analytics. ``money()`` produces "EGP 1,299.00" for a human; ``value`` here is
 * 1299. Sending the formatted string turns every revenue figure into a zero,
 * and it does it silently.
 */
function num(value) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

/** One item, in the shape every ecommerce event shares. */
export function toItem(source, { index, listId, listName, quantity } = {}) {
  const item = {
    item_id: source.sku ?? source.item_id,
    item_name: source.title ?? source.item_name,
    item_brand: source.brand ?? undefined,
    price: num(source.sale_price ?? source.price),
    currency: source.currency ?? 'EGP',
  };
  if (source.item_group_id) item.item_group_id = source.item_group_id;
  if (source.size) item.item_variant = source.size;
  if (index != null) item.index = index;
  if (listId) item.item_list_id = listId;
  if (listName) item.item_list_name = listName;
  if (quantity != null) item.quantity = quantity;
  return item;
}

const sum = (items) =>
  items.reduce((total, item) => total + item.price * (item.quantity ?? 1), 0);

export function viewItemList(products, { listId, listName, locale }) {
  const items = products.map((product, index) =>
    toItem(
      // A listing row advertises the cheapest variant's price, and the API
      // returns that variant's SKU as `sku` for exactly this reason. The
      // fallback covers a detail payload being passed in here.
      { ...product, sku: product.sku ?? product.default_variant_sku },
      { index, listId, listName },
    ),
  );
  return { event: 'view_item_list', item_list_id: listId, item_list_name: listName, locale, items };
}

/**
 * GA4's `search`, section 5.
 *
 * `term` is what the *server* searched for, echoed back in the response, not
 * the raw contents of the box. The two differ whenever the query was trimmed or
 * refused, and a search report is read to decide what to stock -- counting a
 * term nobody actually searched for makes that decision on fiction.
 *
 * `results` is included because a term with no results is the most actionable
 * row in the whole report: a shopper naming something the shop does not sell.
 */
export function search(term, { locale, resultCount } = {}) {
  return {
    event: 'search',
    search_term: (term ?? '').trim(),
    results: resultCount,
    locale,
  };
}

export function selectItem(product, { index, listId, listName, locale }) {
  return {
    event: 'select_item',
    item_list_id: listId,
    item_list_name: listName,
    locale,
    items: [toItem(product, { index, listId, listName })],
  };
}

export function viewItem(product, variant, { locale }) {
  const item = toItem({ ...product, ...variant }, { quantity: 1 });
  return { event: 'view_item', currency: item.currency, value: item.price, locale, items: [item] };
}

export function addToCart(product, variant, { quantity = 1, listId, listName, locale }) {
  const item = toItem({ ...product, ...variant }, { quantity, listId, listName });
  return {
    event: 'add_to_cart',
    currency: item.currency,
    value: item.price * quantity,
    locale,
    items: [item],
  };
}

export function beginCheckout(cart, { locale }) {
  const items = (cart.items ?? []).map((line, index) =>
    toItem(
      {
        sku: line.sku,
        title: line.title,
        price: line.unit_price_effective ?? line.unit_price_snapshot,
        currency: 'EGP',
      },
      { index, quantity: line.quantity },
    ),
  );
  return {
    event: 'begin_checkout',
    currency: 'EGP',
    // The cart's own total, not a re-derivation: the shopper is checking out
    // the number they were shown, promotions included.
    value: num(cart.total ?? sum(items)),
    locale,
    items,
  };
}

export function viewCart(cart, { locale }) {
  const items = (cart.items ?? []).map((line, index) =>
    toItem(
      {
        sku: line.sku,
        title: line.title,
        price: line.unit_price_effective ?? line.unit_price_snapshot,
        currency: 'EGP',
      },
      { index, quantity: line.quantity },
    ),
  );
  return {
    event: 'view_cart',
    currency: 'EGP',
    // The cart's own total, same rule as begin_checkout: not a re-derivation.
    value: num(cart.total ?? sum(items)),
    locale,
    items,
  };
}

export function removeFromCart(line, { locale }) {
  const item = toItem(
    {
      sku: line.sku,
      title: line.title,
      price: line.unit_price_effective ?? line.unit_price_snapshot,
      currency: 'EGP',
    },
    { quantity: line.quantity },
  );
  return {
    event: 'remove_from_cart',
    currency: 'EGP',
    value: item.price * (line.quantity ?? 1),
    locale,
    items: [item],
  };
}

export function purchase(order, { locale }) {
  const items = (order.items ?? []).map((line, index) =>
    toItem(
      {
        sku: line.sku,
        title: line.product_title,
        brand: line.brand,
        item_group_id: line.item_group_id,
        price: line.unit_price,
        currency: order.currency ?? 'EGP',
      },
      { index, quantity: line.quantity, listId: line.item_list_id, listName: line.item_list_name },
    ),
  );
  return {
    event: 'purchase',
    // The order number, never the database id: section 2 makes it the immutable
    // commerce identity and the GA4/Ads transaction_id, and it is what
    // de-duplicates a purchase against the server-side event in S5.
    transaction_id: order.order_number,
    currency: order.currency ?? 'EGP',
    value: num(order.total),
    shipping: num(order.shipping),
    tax: num(order.tax_total),
    locale,
    items,
  };
}
