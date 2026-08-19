import { useData } from '../../hooks/useData.js';
import ProductCard from '../../components/common/ProductCard/ProductCard.jsx';
import styles from './index.module.scss';

export default function HomePage() {
  const { listing, copy } = useData();

  return (
    <>
      <h1>{copy.heading}</h1>

      {listing.items.length === 0 ? (
        <p>{/* An empty catalogue is a state, not an error. */}</p>
      ) : (
        <div className={styles.grid}>
          {listing.items.map((product, index) => (
            <ProductCard key={product.id} product={product} index={index} />
          ))}
        </div>
      )}
    </>
  );
}
