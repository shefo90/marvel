import {
  Alert,
  Button,
  Card,
  Form,
  Input,
  InputNumber,
  Modal,
  Select,
  Space,
  Switch,
  Table,
  Tag,
  Typography,
} from 'antd';
import { useState } from 'react';

import { useAuth } from '../../hooks/useAuth.js';
import { useGenerateVariants, useUpdateVariant } from '../../hooks/useVariants.js';
import { AVAILABILITIES } from '../../utils/constants.js';
import styles from './ProductEdit.module.scss';

const asOptions = (values) => values.map((value) => ({ value, label: value }));

/**
 * The size x colour matrix, and per-row edits.
 *
 * SKUs are generated, never typed: trg_variants_sku_immutable makes a typo
 * permanent, and Merchant Center, the Meta catalog and GA4 all key on the SKU.
 * The table says so rather than letting the operator discover it as a database
 * error on their second save.
 */
export default function VariantsTab({ product }) {
  const [matrixForm] = Form.useForm();
  const [editForm] = Form.useForm();
  const [editing, setEditing] = useState(null);
  const { canSetCost } = useAuth();

  const generate = useGenerateVariants(product.id);
  const save = useUpdateVariant(product.id);

  const openEditor = (variant) => {
    setEditing(variant);
    editForm.setFieldsValue({
      variant_title: variant.variant_title,
      price: variant.price,
      sale_price: variant.sale_price,
      stock_quantity: variant.stock_quantity,
      is_active: variant.is_active,
    });
  };

  const columns = [
    { title: 'SKU', dataIndex: 'sku', className: styles.mono },
    { title: 'Variant', dataIndex: 'variant_title' },
    { title: 'Size', dataIndex: 'size' },
    { title: 'Colour', dataIndex: 'color' },
    { title: 'Price', dataIndex: 'price' },
    { title: 'Sale price', dataIndex: 'sale_price', render: (value) => value ?? '—' },
    { title: 'Stock', dataIndex: 'stock_quantity' },
    {
      title: 'Active',
      dataIndex: 'is_active',
      render: (value) => (
        <Tag color={value ? 'green' : 'default'}>{value ? 'active' : 'inactive'}</Tag>
      ),
    },
    {
      title: '',
      key: 'actions',
      render: (_, variant) => (
        <Button size="small" onClick={() => openEditor(variant)}>
          Edit
        </Button>
      ),
    },
  ];

  return (
    <div>
      <Card title="Add variants" className={styles.matrix}>
        <Typography.Paragraph type="secondary">
          Every size is combined with every colour. Combinations that already exist are
          skipped. SKUs are generated from the item group ID and are{' '}
          <strong>immutable once saved</strong>.
        </Typography.Paragraph>

        {generate.isError ? (
          <Alert
            type="error"
            showIcon
            message={generate.error.message}
            className={styles.alert}
          />
        ) : null}

        <Form
          form={matrixForm}
          layout="vertical"
          requiredMark={false}
          initialValues={{ price: '0', stock_quantity: 0, availability: 'in_stock' }}
          onFinish={(values) => generate.mutate(values)}
        >
          <Space size="middle" wrap align="start" className={styles.row}>
            <Form.Item
              label="Sizes"
              name="sizes"
              rules={[{ required: true, message: 'At least one size' }]}
              className={styles.wideField}
            >
              <Select aria-label="Sizes" mode="tags" tokenSeparators={[',']} placeholder="38, 39" />
            </Form.Item>
            <Form.Item
              label="Colours"
              name="colors"
              rules={[{ required: true, message: 'At least one colour' }]}
              className={styles.wideField}
            >
              <Select aria-label="Colours" mode="tags" tokenSeparators={[',']} placeholder="black" />
            </Form.Item>
            <Form.Item label="Price" name="price" className={styles.field}>
              <Input aria-label="Price" inputMode="decimal" addonAfter="EGP" />
            </Form.Item>
            <Form.Item label="Sale price" name="sale_price" className={styles.field}>
              <Input aria-label="Sale price" inputMode="decimal" addonAfter="EGP" />
            </Form.Item>
            <Form.Item label="Stock" name="stock_quantity" className={styles.field}>
              <InputNumber aria-label="Stock" min={0} />
            </Form.Item>
            <Form.Item label="Availability" name="availability" className={styles.field}>
              <Select aria-label="Availability" options={asOptions(AVAILABILITIES)} />
            </Form.Item>
          </Space>
          <Button type="primary" htmlType="submit" loading={generate.isPending}>
            Generate variants
          </Button>
        </Form>
      </Card>

      <Table
        rowKey="id"
        columns={columns}
        dataSource={product.variants ?? []}
        pagination={false}
      />

      <Modal
        open={editing !== null}
        title={editing ? `Edit ${editing.sku}` : ''}
        okText="Save variant"
        confirmLoading={save.isPending}
        onCancel={() => setEditing(null)}
        onOk={() => editForm.submit()}
        destroyOnHidden
      >
        {save.isError ? (
          <Alert type="error" showIcon message={save.error.message} className={styles.alert} />
        ) : null}
        <Form
          form={editForm}
          layout="vertical"
          requiredMark={false}
          onFinish={(values) =>
            save.mutate(
              { variantId: editing.id, values },
              { onSuccess: () => setEditing(null) },
            )
          }
        >
          <Form.Item label="Variant title" name="variant_title">
            <Input />
          </Form.Item>
          <Form.Item label="Price" name="price">
            <Input aria-label="Price" inputMode="decimal" addonAfter="EGP" />
          </Form.Item>
          <Form.Item
            label="Sale price"
            name="sale_price"
            extra="Cannot exceed the price."
          >
            <Input aria-label="Sale price" inputMode="decimal" addonAfter="EGP" />
          </Form.Item>
          <Form.Item label="Stock" name="stock_quantity">
            <InputNumber aria-label="Stock" min={0} />
          </Form.Item>
          {/* COGS feeds contribution_profit, so the API requires admin for it
              even though this route is open to catalog. Hiding it here is a
              courtesy -- the 403 is what actually enforces the rule. */}
          {canSetCost ? (
            <Form.Item
              label="Cost (COGS)"
              name="cost"
              extra="Admins only. Feeds contribution profit."
            >
              <Input aria-label="Cost" inputMode="decimal" addonAfter="EGP" />
            </Form.Item>
          ) : null}
          <Form.Item label="Active" name="is_active" valuePropName="checked">
            <Switch />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}
