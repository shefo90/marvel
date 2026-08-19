import { Alert, Button, Popconfirm, Skeleton, Space, Tabs, Tag } from 'antd';
import { useParams } from 'react-router-dom';

import PageHeader from '../../components/common/PageHeader/PageHeader.jsx';
import { useArchiveProduct, useProduct } from '../../hooks/useProduct.js';
import BasicsTab from './BasicsTab.jsx';
import ContentTab from './ContentTab.jsx';
import VariantsTab from './VariantsTab.jsx';
import styles from './ProductEdit.module.scss';

const STATUS_COLOURS = { draft: 'default', active: 'green', archived: 'red' };

/**
 * The product editor.
 *
 * One load returns the product, its translations and its variants, and the tabs
 * are views over that one payload rather than three screens with three
 * requests. Archive lives in the header because it applies to the product as a
 * whole, not to any one tab.
 */
export default function ProductEdit() {
  const { id } = useParams();
  const { data: product, isPending, isError, error } = useProduct(id);
  const archive = useArchiveProduct(id);

  if (isPending) return <Skeleton active paragraph={{ rows: 8 }} />;
  if (isError) return <Alert type="error" showIcon message={error.message} />;

  return (
    <>
      <PageHeader
        title={
          <Space>
            {product.title}
            <Tag color={STATUS_COLOURS[product.status]}>{product.status}</Tag>
          </Space>
        }
        extra={
          product.status === 'archived' ? null : (
            <Popconfirm
              title="Archive this product?"
              // Never "delete": fk_order_items_product_id is ON DELETE RESTRICT,
              // so anything sold cannot be removed at all, and deleting would
              // orphan the history GA4, Merchant Center and the Meta catalog
              // key on. Archiving also unpublishes every language.
              description="It stops being sold and every language is unpublished. Nothing is deleted."
              okText="Yes, archive"
              cancelText="Cancel"
              onConfirm={() => archive.mutate()}
            >
              <Button danger loading={archive.isPending}>
                Archive
              </Button>
            </Popconfirm>
          )
        }
      />

      <div className={styles.panel}>
        <Tabs
          items={[
            {
              key: 'basics',
              label: 'Basics',
              children: <BasicsTab product={product} />,
            },
            {
              key: 'content',
              label: 'Content',
              children: <ContentTab product={product} />,
            },
            {
              key: 'variants',
              label: 'Variants',
              children: <VariantsTab product={product} />,
            },
          ]}
        />
      </div>
    </>
  );
}
