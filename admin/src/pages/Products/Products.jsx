import { Alert, Button, Input, Select, Space, Table, Tag } from 'antd';
import { useState } from 'react';
import { Link } from 'react-router-dom';

import PageHeader from '../../components/common/PageHeader/PageHeader.jsx';
import { useDebounce } from '../../hooks/useDebounce.js';
import { useProducts } from '../../hooks/useProducts.js';
import { LOCALES, PRODUCT_STATUSES } from '../../utils/constants.js';
import styles from './Products.module.scss';

const STATUS_COLOURS = { draft: 'default', active: 'green', archived: 'red' };

/**
 * Every product the operator owns, drafts included.
 *
 * The public listing hides anything not active and published, because that is
 * what a shopper may see. This is the opposite view: the one that shows what is
 * still unfinished, which is the only reason the screen exists.
 */
export default function Products() {
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(50);
  const [status, setStatus] = useState(undefined);
  const [typed, setTyped] = useState('');
  const search = useDebounce(typed);

  const { data, isPending, isError, error } = useProducts({
    page,
    pageSize,
    status,
    search,
  });

  const columns = [
    {
      title: 'Title',
      dataIndex: 'title',
      render: (title, row) => <Link to={`/products/${row.id}`}>{title}</Link>,
    },
    { title: 'Slug', dataIndex: 'slug', className: styles.mono },
    {
      title: 'Status',
      dataIndex: 'status',
      render: (value) => <Tag color={STATUS_COLOURS[value]}>{value}</Tag>,
    },
    {
      title: 'Languages',
      key: 'languages',
      // Published or draft, never "ready". `is_complete` is a generated column
      // computed from description and meta_description alone -- it omits title,
      // which the publish CHECK requires, so a row can be "complete" and still
      // unpublishable. Readiness is the editor's blocker list, which asks the
      // API rather than guessing from a column that cannot answer.
      render: (_, row) => (
        <Space size={4}>
          {LOCALES.map(({ code }) => {
            const translation = row.translations?.find((t) => t.locale === code);
            const published = translation?.is_published === true;
            return (
              <Tag
                key={code}
                data-testid={`locale-${code}`}
                color={published ? 'green' : 'default'}
              >
                {code} · {translation ? (published ? 'published' : 'draft') : 'missing'}
              </Tag>
            );
          })}
        </Space>
      ),
    },
    { title: 'Variants', dataIndex: 'variant_count', width: 100 },
    { title: 'Images', dataIndex: 'image_count', width: 100 },
  ];

  return (
    <>
      <PageHeader
        title="Products"
        extra={
          <Link to="/products/new">
            <Button type="primary">New product</Button>
          </Link>
        }
      />

      <Space className={styles.filters} size="middle" wrap>
        <Input
          placeholder="Search title or slug"
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
          options={PRODUCT_STATUSES.map((value) => ({ value, label: value }))}
          className={styles.status}
        />
      </Space>

      {isError ? (
        <Alert type="error" showIcon title={error.message} className={styles.error} />
      ) : null}

      <Table
        rowKey="id"
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
