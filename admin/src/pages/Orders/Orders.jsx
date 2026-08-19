import { Alert, Input, Select, Space, Table, Tag } from 'antd';
import { useState } from 'react';
import { Link } from 'react-router-dom';

import PageHeader from '../../components/common/PageHeader/PageHeader.jsx';
import { useDebounce } from '../../hooks/useDebounce.js';
import { useOrders } from '../../hooks/useOrders.js';
import { ORDER_STATUSES } from '../../utils/constants.js';
import styles from './Orders.module.scss';

const STATUS_COLOURS = {
  pending: 'gold',
  confirmed: 'blue',
  processing: 'geekblue',
  shipped: 'cyan',
  delivered: 'green',
  cancelled: 'red',
  returned: 'volcano',
};

const COD_COLOURS = { pending: 'gold', collected: 'green', remitted: 'blue', failed: 'red' };

/**
 * The work queue.
 *
 * Newest first, because this screen is opened to see what just came in rather
 * than to browse history. Everything is filtered and paged on the server: an
 * order book is not something to slice in the browser.
 */
export default function Orders() {
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(50);
  const [status, setStatus] = useState(undefined);
  const [typed, setTyped] = useState('');
  const search = useDebounce(typed);

  const { data, isPending, isError, error } = useOrders({ page, pageSize, status, search });

  const columns = [
    {
      title: 'Order',
      dataIndex: 'order_number',
      render: (value) => <Link to={`/orders/${value}`}>{value}</Link>,
      className: styles.mono,
    },
    {
      title: 'Status',
      dataIndex: 'status',
      render: (value) => <Tag color={STATUS_COLOURS[value]}>{value}</Tag>,
    },
    { title: 'Payment', dataIndex: 'payment_method' },
    {
      title: 'Cash on delivery',
      dataIndex: 'cod_collection_status',
      // Only COD orders carry this; a card order showing "—" is clearer than a
      // blank cell that looks like missing data.
      render: (value) =>
        value ? <Tag color={COD_COLOURS[value]}>{value}</Tag> : <span>—</span>,
    },
    {
      title: 'Total',
      dataIndex: 'total',
      render: (value, row) => `${value} ${row.currency}`,
    },
    { title: 'Customer', dataIndex: 'customer_email' },
    {
      title: 'Placed',
      dataIndex: 'placed_at',
      render: (value) => (value ? new Date(value).toLocaleString() : '—'),
    },
  ];

  return (
    <>
      <PageHeader title="Orders" />

      <Space className={styles.filters} size="middle" wrap>
        <Input
          placeholder="Order number or email"
          allowClear
          value={typed}
          onChange={(event) => {
            setTyped(event.target.value);
            setPage(1);
          }}
          className={styles.search}
        />
        <Select
          aria-label="Status"
          placeholder="Any status"
          allowClear
          value={status}
          onChange={(value) => {
            setStatus(value);
            setPage(1);
          }}
          options={ORDER_STATUSES.map((value) => ({ value, label: value }))}
          className={styles.status}
        />
      </Space>

      {isError ? (
        <Alert type="error" showIcon title={error.message} className={styles.error} />
      ) : null}

      <Table
        rowKey="order_number"
        loading={isPending}
        columns={columns}
        dataSource={data?.items ?? []}
        pagination={{
          current: data?.page ?? page,
          pageSize: data?.page_size ?? pageSize,
          total: data?.total ?? 0,
          showSizeChanger: true,
          onChange: (nextPage, nextSize) => {
            setPage(nextPage);
            setPageSize(nextSize);
          },
        }}
      />
    </>
  );
}
