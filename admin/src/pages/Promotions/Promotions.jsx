import { Alert, Button, DatePicker, Form, Input, InputNumber, Modal, Select, Space, Table, Tag } from 'antd';
import { useState } from 'react';

import PageHeader from '../../components/common/PageHeader/PageHeader.jsx';
import { useCategories } from '../../hooks/useCategories.js';
import { usePromotionMutations, usePromotions } from '../../hooks/usePromotions.js';
import styles from './Promotions.module.scss';

const TYPES = ['percentage', 'fixed', 'bogo'];

/**
 * The operator's offers.
 *
 * Not a rules engine: no priority, no stacking, no tiers. The operator decides
 * and the system records what they chose, and pricing applies whichever single
 * offer leaves the shopper better off.
 *
 * Nothing here deletes. ``is_active`` is the switch, and a promotion that
 * priced real orders is history those orders point at.
 */
export default function Promotions() {
  const [form] = Form.useForm();
  const [creating, setCreating] = useState(false);
  const [type, setType] = useState('percentage');

  const { data: promotions = [], isPending } = usePromotions();
  const { data: categories = [] } = useCategories();
  const { create, update } = usePromotionMutations();

  const categoryName = (id) => {
    const category = categories.find((entry) => entry.id === id);
    return category ? `${category.parent_name} / ${category.name}` : `category ${id}`;
  };

  const describeTarget = (target) => {
    if (target.target_type === 'all') return 'everything';
    if (target.target_type === 'category') return categoryName(target.target_id);
    return `${target.target_type} ${target.target_id}`;
  };

  const describeValue = (promotion) => {
    if (promotion.type === 'percentage') {
      return `${Number(promotion.discount_percent)}%`;
    }
    if (promotion.type === 'fixed') {
      return `${Number(promotion.discount_amount)} EGP off`;
    }
    return `buy ${promotion.buy_quantity}, get ${promotion.get_quantity} at ${Number(
      promotion.get_discount_percent,
    )}% off`;
  };

  const describeWindow = (promotion) => {
    if (!promotion.starts_at && !promotion.ends_at) return 'always on';
    const from = promotion.starts_at ? promotion.starts_at.slice(0, 10) : 'now';
    const to = promotion.ends_at ? promotion.ends_at.slice(0, 10) : 'no end';
    return `${from} → ${to}`;
  };

  const columns = [
    { title: 'Offer', dataIndex: 'name' },
    { title: 'Type', dataIndex: 'type', render: (value) => <Tag>{value}</Tag> },
    { title: 'Value', key: 'value', render: (_, row) => describeValue(row) },
    {
      title: 'Applies to',
      key: 'targets',
      // Named, not counted: "1 target" tells the operator nothing they can act
      // on, and a promotion pointed at the wrong thing is the expensive mistake.
      render: (_, row) => row.targets.map(describeTarget).join(', '),
    },
    { title: 'Window', key: 'window', render: (_, row) => describeWindow(row) },
    {
      title: 'Status',
      dataIndex: 'is_active',
      render: (value) => (
        <Tag color={value ? 'green' : 'default'}>{value ? 'running' : 'paused'}</Tag>
      ),
    },
    {
      title: '',
      key: 'actions',
      render: (_, row) => (
        <Button
          size="small"
          onClick={() =>
            update.mutate({ promotionId: row.id, values: { is_active: !row.is_active } })
          }
        >
          {row.is_active ? 'Pause' : 'Resume'}
        </Button>
      ),
    },
  ];

  const onCreate = (values) => {
    const targets =
      values.target_type === 'category'
        ? [{ target_type: 'category', target_id: values.target_id }]
        : [{ target_type: 'all', target_id: null }];

    const payload = {
      name: values.name,
      type,
      is_active: true,
      targets,
      starts_at: values.window?.[0]?.toISOString() ?? null,
      ends_at: values.window?.[1]?.toISOString() ?? null,
    };
    if (type === 'percentage') payload.discount_percent = String(values.discount_percent);
    if (type === 'fixed') payload.discount_amount = String(values.discount_amount);
    if (type === 'bogo') {
      payload.buy_quantity = values.buy_quantity;
      payload.get_quantity = values.get_quantity;
      payload.get_discount_percent = String(values.get_discount_percent);
    }

    create.mutate(payload, {
      onSuccess: () => {
        setCreating(false);
        form.resetFields();
      },
    });
  };

  return (
    <>
      <PageHeader
        title="Offers"
        extra={
          <Button type="primary" onClick={() => setCreating(true)}>
            New offer
          </Button>
        }
      />

      {update.isError ? (
        <Alert type="error" showIcon title={update.error.message} className={styles.alert} />
      ) : null}

      <Table
        rowKey="id"
        loading={isPending}
        columns={columns}
        dataSource={promotions}
        pagination={false}
      />

      <Modal
        open={creating}
        title="New offer"
        okText="Create offer"
        confirmLoading={create.isPending}
        onCancel={() => setCreating(false)}
        onOk={() => form.submit()}
        destroyOnHidden
      >
        {create.isError ? (
          <Alert type="error" showIcon title={create.error.message} className={styles.alert} />
        ) : null}

        <Form
          form={form}
          layout="vertical"
          requiredMark={false}
          initialValues={{ type: 'percentage', target_type: 'all' }}
          onFinish={onCreate}
        >
          <Form.Item
            label="Name"
            name="name"
            rules={[{ required: true, message: 'Give the offer a name you will recognise' }]}
          >
            <Input aria-label="Name" placeholder="Eid 20% off sandals" />
          </Form.Item>

          <Form.Item label="Type" name="type">
            <Select
              aria-label="Type"
              value={type}
              onChange={setType}
              options={TYPES.map((value) => ({ value, label: value }))}
            />
          </Form.Item>

          {/* The fields shown are the fields the type actually uses. The
              database ties them together with CHECK constraints, so offering
              all of them at once would be offering a row that cannot be saved. */}
          {type === 'percentage' ? (
            <Form.Item
              label="Discount percent"
              name="discount_percent"
              rules={[{ required: true, message: 'How much off?' }]}
            >
              <InputNumber aria-label="Discount percent" min={0.01} max={100} />
            </Form.Item>
          ) : null}

          {type === 'fixed' ? (
            <Form.Item
              label="Discount amount"
              name="discount_amount"
              rules={[{ required: true, message: 'How much off?' }]}
            >
              <InputNumber aria-label="Discount amount" min={0.01} suffix="EGP" />
            </Form.Item>
          ) : null}

          {type === 'bogo' ? (
            <Space size="middle" wrap align="start">
              <Form.Item
                label="Buy quantity"
                name="buy_quantity"
                rules={[{ required: true, message: 'Buy how many?' }]}
              >
                <InputNumber aria-label="Buy quantity" min={1} />
              </Form.Item>
              <Form.Item
                label="Get quantity"
                name="get_quantity"
                rules={[{ required: true, message: 'Get how many?' }]}
              >
                <InputNumber aria-label="Get quantity" min={1} />
              </Form.Item>
              <Form.Item
                label="Discount on the free units"
                name="get_discount_percent"
                rules={[{ required: true, message: '100 means free' }]}
                extra="100 means free."
              >
                <InputNumber aria-label="Discount on the free units" min={0.01} max={100} />
              </Form.Item>
            </Space>
          ) : null}

          <Form.Item
            label="Applies to"
            name="target_type"
            extra="An offer with no target discounts nothing, so choose 'everything' deliberately."
          >
            <Select
              aria-label="Applies to"
              options={[
                { value: 'all', label: 'Everything' },
                { value: 'category', label: 'One category' },
              ]}
            />
          </Form.Item>

          <Form.Item
            noStyle
            shouldUpdate={(prev, next) => prev.target_type !== next.target_type}
          >
            {({ getFieldValue }) =>
              getFieldValue('target_type') === 'category' ? (
                <Form.Item
                  label="Category"
                  name="target_id"
                  rules={[{ required: true, message: 'Which category?' }]}
                >
                  <Select
                    aria-label="Category"
                    options={categories.map((category) => ({
                      value: category.id,
                      label: `${category.parent_name} / ${category.name}`,
                    }))}
                  />
                </Form.Item>
              ) : null
            }
          </Form.Item>

          <Form.Item
            label="Window"
            name="window"
            extra="Leave empty to run until you pause it."
          >
            <DatePicker.RangePicker showTime />
          </Form.Item>
        </Form>
      </Modal>
    </>
  );
}
