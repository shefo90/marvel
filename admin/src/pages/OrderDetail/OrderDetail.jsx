import { Alert, Button, Descriptions, Input, Modal, Skeleton, Space, Table, Tag, Timeline, Typography } from 'antd';
import { useState } from 'react';
import { useParams } from 'react-router-dom';

import PageHeader from '../../components/common/PageHeader/PageHeader.jsx';
import { useAdvanceOrder, useOrder } from '../../hooks/useOrders.js';
import { ORDER_NEXT } from '../../utils/constants.js';
import styles from './OrderDetail.module.scss';

const STATUS_COLOURS = {
  pending: 'gold',
  confirmed: 'blue',
  processing: 'geekblue',
  shipped: 'cyan',
  delivered: 'green',
  cancelled: 'red',
  returned: 'volcano',
};

/**
 * One order: its money, its lines, and every move it has made.
 *
 * Nothing here edits money. Totals are watched by the migration-0004 audit
 * trigger and change through refunds, which arrive with S4 — a status screen
 * that could edit a total would be a way to move money without an audit row.
 */
export default function OrderDetail() {
  const { orderNumber } = useParams();
  const { data: order, isPending, isError, error } = useOrder(orderNumber);
  const advance = useAdvanceOrder(orderNumber);

  const [moving, setMoving] = useState(null);
  const [reason, setReason] = useState('');

  if (isPending) return <Skeleton active paragraph={{ rows: 8 }} />;
  if (isError) return <Alert type="error" showIcon title={error.message} />;

  // Only the moves the API will actually accept. Offering a button that comes
  // back 409 teaches the operator to distrust the screen.
  const nextStatuses = ORDER_NEXT[order.status] ?? [];

  const itemColumns = [
    { title: '#', dataIndex: 'line_number', width: 60 },
    { title: 'SKU', dataIndex: 'sku', className: styles.mono },
    { title: 'Product', dataIndex: 'product_title' },
    { title: 'Variant', dataIndex: 'variant_label' },
    { title: 'Qty', dataIndex: 'quantity', width: 70 },
    { title: 'Unit', dataIndex: 'unit_price' },
    {
      title: 'Discount',
      dataIndex: 'discount_amount',
      // The source matters: a markdown is not a campaign cost, and only the
      // promotion rows feed promotion_cost_total.
      render: (value, row) =>
        Number(value) > 0 ? (
          <Space size={4}>
            <span>{value}</span>
            {row.discount_source ? <Tag>{row.discount_source}</Tag> : null}
          </Space>
        ) : (
          '—'
        ),
    },
    { title: 'Line total', dataIndex: 'line_total' },
    {
      title: 'Refunded',
      dataIndex: 'refunded_quantity',
      render: (value) => (value > 0 ? <Tag color="volcano">{value}</Tag> : '—'),
    },
  ];

  return (
    <>
      <PageHeader
        title={
          <Space>
            <span className={styles.mono}>{order.order_number}</span>
            <Tag color={STATUS_COLOURS[order.status]}>{order.status}</Tag>
          </Space>
        }
        extra={
          <Space wrap>
            {nextStatuses.map((next) => (
              <Button
                key={next}
                danger={next === 'cancelled' || next === 'returned'}
                type={next === 'confirmed' || next === 'delivered' ? 'primary' : 'default'}
                onClick={() => {
                  setMoving(next);
                  setReason('');
                }}
              >
                Mark {next}
              </Button>
            ))}
          </Space>
        }
      />

      {advance.isError ? (
        <Alert type="error" showIcon title={advance.error.message} className={styles.alert} />
      ) : null}

      <div className={styles.panel}>
        <Descriptions bordered size="small" column={2}>
          <Descriptions.Item label="Customer">{order.customer_email ?? '—'}</Descriptions.Item>
          <Descriptions.Item label="Phone">{order.customer_phone ?? '—'}</Descriptions.Item>
          <Descriptions.Item label="Payment">{order.payment_method}</Descriptions.Item>
          <Descriptions.Item label="Payment status">{order.payment_status}</Descriptions.Item>
          <Descriptions.Item label="Cash on delivery">
            {order.cod_collection_status ?? '—'}
          </Descriptions.Item>
          <Descriptions.Item label="Language">{order.locale}</Descriptions.Item>
          <Descriptions.Item label="Subtotal">{order.subtotal}</Descriptions.Item>
          <Descriptions.Item label="Discount">{order.discount}</Descriptions.Item>
          <Descriptions.Item label="Shipping">{order.shipping}</Descriptions.Item>
          <Descriptions.Item label="Total">
            <strong>
              {order.total} {order.currency}
            </strong>
          </Descriptions.Item>
          <Descriptions.Item label="Campaign cost">
            {order.promotion_cost_total}
          </Descriptions.Item>
          <Descriptions.Item label="Refunded">{order.refunded_amount_total}</Descriptions.Item>
        </Descriptions>
      </div>

      <div className={styles.panel}>
        <Typography.Title level={4}>Items</Typography.Title>
        <Table
          rowKey="line_number"
          columns={itemColumns}
          dataSource={order.items}
          pagination={false}
          size="small"
        />
      </div>

      <div className={styles.panel}>
        <Typography.Title level={4}>History</Typography.Title>
        {order.status_history.length === 0 ? (
          <Typography.Paragraph type="secondary">
            No status changes yet — this order is as it was placed.
          </Typography.Paragraph>
        ) : (
          <Timeline
            items={order.status_history.map((entry) => ({
              children: (
                <>
                  <strong>
                    {entry.from_status ?? 'placed'} → {entry.to_status}
                  </strong>
                  <div className={styles.historyMeta}>
                    {new Date(entry.created_at).toLocaleString()} · {entry.actor_type}
                    {entry.actor_user_id ? ` #${entry.actor_user_id}` : ''}
                  </div>
                  {entry.reason ? <div>{entry.reason}</div> : null}
                </>
              ),
            }))}
          />
        )}
      </div>

      <Modal
        open={moving !== null}
        title={`Mark this order ${moving}?`}
        okText={`Mark ${moving}`}
        confirmLoading={advance.isPending}
        onCancel={() => setMoving(null)}
        onOk={() =>
          advance.mutate({ status: moving, reason }, { onSuccess: () => setMoving(null) })
        }
      >
        <Typography.Paragraph type="secondary">
          This is recorded against your account, with the time and the reason. It
          does not change any money on the order.
        </Typography.Paragraph>
        <Input.TextArea
          aria-label="Reason"
          rows={3}
          placeholder="Why? (optional, but the next person will thank you)"
          value={reason}
          onChange={(event) => setReason(event.target.value)}
        />
      </Modal>
    </>
  );
}
