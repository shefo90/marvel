import { Alert, Button, Modal, Spin, Typography } from 'antd';
import { useEffect, useState } from 'react';

import styles from './MembersModal.module.scss';

/**
 * Which products are in a collection, and in what order.
 *
 * **The order is the data.** It drives the collection's own "featured" sort and
 * section 5's `index`, so this is not a set with a display preference — moving
 * a product changes what the shopper sees first and what the analytics report.
 * That is also why the API takes the whole ordered list in one PUT rather than
 * add/remove calls: a diff cannot express a reordering.
 *
 * **Move up / move down rather than drag-and-drop.** A collection is a
 * merchandising decision made a few times a season, not a daily sorting chore,
 * and buttons are operable by keyboard, readable by a screen reader, and
 * testable without simulating pointer physics. Drag would look better in a
 * screenshot and be worse to use.
 *
 * **Plain `ul`/`li` rather than AntD's `List`**, which renders its own wrapper
 * and does not forward `aria-label` to the element carrying the list role — so
 * the two lists here would both have been unnamed to a screen reader, on a
 * screen whose entire purpose is telling them apart.
 *
 * Nothing is written until "Save order". Reordering is exploratory — the
 * operator shuffles three things to see how the row reads — and a save per
 * click would put three half-finished orders through the storefront cache.
 */
export default function MembersModal({
  open,
  name,
  memberIds = [],
  products = [],
  onSave,
  onClose,
  saving = false,
  loading = false,
  error = null,
}) {
  const [ordered, setOrdered] = useState(memberIds);

  // The membership arrives a tick after the modal opens. Re-seeding when it
  // lands means the list is not briefly empty and then repopulated, which reads
  // as "this collection holds nothing".
  const seed = memberIds.join(',');
  useEffect(() => {
    setOrdered(memberIds);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [seed]);

  const byId = new Map(products.map((product) => [product.id, product]));
  const titleOf = (id) => byId.get(id)?.title ?? `product ${id}`;
  const available = products.filter((product) => !ordered.includes(product.id));

  const move = (index, delta) => {
    const target = index + delta;
    if (target < 0 || target >= ordered.length) return;
    const next = [...ordered];
    [next[index], next[target]] = [next[target], next[index]];
    setOrdered(next);
  };

  return (
    <Modal
      open={open}
      title={`Products — ${name}`}
      okText="Save order"
      confirmLoading={saving}
      onCancel={onClose}
      onOk={() => onSave(ordered)}
      destroyOnHidden
      width={640}
    >
      {error ? (
        <Alert type="error" showIcon message={error.message} style={{ marginBottom: 16 }} />
      ) : null}

      <Typography.Paragraph type="secondary">
        The order here is the order shoppers see, and it is what this collection
        reports as each product&apos;s list position.
      </Typography.Paragraph>

      {loading ? (
        <div className={styles.empty}>
          <Spin />
        </div>
      ) : (
        <ul className={styles.list} aria-label="Products in this collection">
          {ordered.length === 0 ? (
            <li className={styles.empty}>Nothing in this collection yet</li>
          ) : (
            ordered.map((id, index) => (
              <li key={id} className={styles.row}>
                <span className={styles.position}>{index + 1}</span>
                <span className={styles.title}>{titleOf(id)}</span>
                <Button
                  size="small"
                  disabled={index === 0}
                  aria-label={`Move ${titleOf(id)} up`}
                  onClick={() => move(index, -1)}
                >
                  ↑
                </Button>
                <Button
                  size="small"
                  disabled={index === ordered.length - 1}
                  aria-label={`Move ${titleOf(id)} down`}
                  onClick={() => move(index, 1)}
                >
                  ↓
                </Button>
                <Button
                  size="small"
                  danger
                  aria-label={`Remove ${titleOf(id)}`}
                  onClick={() => setOrdered(ordered.filter((entry) => entry !== id))}
                >
                  Remove
                </Button>
              </li>
            ))
          )}
        </ul>
      )}

      <Typography.Title level={5}>Add a product</Typography.Title>
      <ul className={styles.list} aria-label="Products not in this collection">
        {available.length === 0 ? (
          <li className={styles.empty}>Every product is already in here</li>
        ) : (
          available.map((product) => (
            <li key={product.id} className={styles.row}>
              <span className={styles.title}>{product.title}</span>
              <Button
                size="small"
                aria-label={`Add ${product.title}`}
                onClick={() => setOrdered([...ordered, product.id])}
              >
                Add
              </Button>
            </li>
          ))
        )}
      </ul>
    </Modal>
  );
}
