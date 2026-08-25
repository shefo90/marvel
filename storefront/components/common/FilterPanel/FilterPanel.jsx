import { useLocale } from '../../../hooks/useLocale.jsx';
import styles from './FilterPanel.module.scss';

/**
 * The filter sidebar.
 *
 * Every control here is a link, not a checkbox with an onChange handler. Three
 * things follow from that and none of them are incidental:
 *
 * 1. The filtered view has its own address, so it can be shared and reloaded.
 * 2. It works before — and without — hydration, which matters most on the slow
 *    connections this shop actually sells over.
 * 3. The server renders the result, so a crawler that follows one sees real
 *    products rather than an empty shell.
 *
 * The counts beside each value come from the API's facets, which exclude their
 * own facet: ticking one size leaves the others showing what they *would*
 * return, because those are exactly the boxes that widen the result.
 */
function toggled(current, value) {
  const next = new Set(current);
  if (next.has(value)) next.delete(value);
  else next.add(value);
  return [...next];
}

function buildHref(basePath, filters, changes) {
  const merged = { ...filters, ...changes };
  const params = new URLSearchParams();
  merged.sizes?.forEach((size) => params.append('size', size));
  merged.colors?.forEach((color) => params.append('color', color));
  if (merged.inStock) params.set('in_stock', '1');
  if (merged.sort && merged.sort !== 'featured') params.set('sort', merged.sort);
  // Any change to the filters invalidates the page number: page 4 of a
  // narrower result is usually empty, which reads as "no products".
  const query = params.toString();
  return query ? `${basePath}?${query}` : basePath;
}

export default function FilterPanel({ basePath, filters, facets, copy, total }) {
  const { href } = useLocale();
  const path = href(basePath);
  const hasFilters =
    filters.sizes.length > 0 || filters.colors.length > 0 || filters.inStock;

  return (
    <aside className={styles.panel} aria-label={copy.filters}>
      <div className={styles.head}>
        <h2 className={styles.heading}>{copy.filters}</h2>
        {hasFilters ? (
          <a className={styles.clear} href={path}>
            {copy.clear}
          </a>
        ) : null}
      </div>

      <p className={styles.count}>
        {total} {copy.results}
      </p>

      <section className={styles.group}>
        <h3 className={styles.groupHeading}>{copy.size}</h3>
        <ul className={styles.sizeList}>
          {facets.sizes.map((size) => (
            <li key={size.code}>
              <a
                className={size.selected ? styles.sizeOn : styles.size}
                href={buildHref(path, filters, {
                  sizes: toggled(filters.sizes, size.code),
                })}
                aria-pressed={size.selected}
              >
                {size.label}
                <span className={styles.facetCount}>{size.count}</span>
              </a>
            </li>
          ))}
        </ul>
      </section>

      <section className={styles.group}>
        <h3 className={styles.groupHeading}>{copy.colour}</h3>
        <ul className={styles.colourList}>
          {facets.colors.map((colour) => (
            <li key={colour.code}>
              <a
                className={colour.selected ? styles.colourOn : styles.colour}
                href={buildHref(path, filters, {
                  colors: toggled(filters.colors, colour.code),
                })}
                aria-pressed={colour.selected}
              >
                <span className={styles.dot} data-colour={colour.code} />
                {colour.label}
                <span className={styles.facetCount}>{colour.count}</span>
              </a>
            </li>
          ))}
        </ul>
      </section>

      <section className={styles.group}>
        <a
          className={filters.inStock ? styles.stockOn : styles.stock}
          href={buildHref(path, filters, { inStock: !filters.inStock })}
          aria-pressed={filters.inStock}
        >
          {copy.inStock}
        </a>
      </section>
    </aside>
  );
}

export { buildHref };
