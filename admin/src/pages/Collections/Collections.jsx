import { Alert, Button, Form, Input, InputNumber, Modal, Space, Table, Tag, Typography } from 'antd';
import { useState } from 'react';

import PageHeader from '../../components/common/PageHeader/PageHeader.jsx';
import MembersModal from '../../components/taxonomy/MembersModal/MembersModal.jsx';
import TranslationsModal from '../../components/taxonomy/TranslationsModal/TranslationsModal.jsx';
import { useProducts } from '../../hooks/useProducts.js';
import {
  useCollectionMutations,
  useCollectionProducts,
  useCollections,
} from '../../hooks/useTaxonomy.js';
import styles from './Collections.module.scss';

/**
 * Collections — the merchandising lists the storefront builds rows from.
 *
 * A category is where a product *belongs*; a collection is where an operator
 * *puts* it. One product sits in exactly one category and in any number of
 * collections, which is why membership is edited here and category is edited on
 * the product.
 *
 * **Nothing here deletes**, for the same reason as categories: `item_list_id`
 * is stamped onto historic cart and order lines, so removing a collection would
 * orphan the attribution those rows carry. `is_active` is the switch.
 */
export default function Collections() {
  const [createForm] = Form.useForm();
  const [editForm] = Form.useForm();
  const [creating, setCreating] = useState(false);
  const [editing, setEditing] = useState(null);
  const [translating, setTranslating] = useState(null);
  const [choosing, setChoosing] = useState(null);

  const { data: collections = [], isPending } = useCollections();
  const { create, update, translate, setProducts } = useCollectionMutations();

  // The picker needs every product, not the current page of the listing.
  const { data: catalogue } = useProducts({ pageSize: 200 });
  const products = catalogue?.items ?? [];

  const members = useCollectionProducts(choosing?.id);

  const toggleActive = (row) =>
    update.mutate({
      collectionId: row.id,
      values: { is_active: !row.is_active },
      expectedUpdatedAt: row.updated_at,
    });

  const onCreate = (values) =>
    create.mutate(
      {
        name: values.name,
        slug: values.slug || undefined,
        list_id: values.list_id || undefined,
        description: values.description || undefined,
        position: values.position ?? 0,
      },
      {
        onSuccess: () => {
          setCreating(false);
          createForm.resetFields();
        },
      },
    );

  const onEdit = (values) =>
    update.mutate(
      {
        collectionId: editing.id,
        values: {
          name: values.name,
          slug: values.slug,
          list_id: values.list_id,
          description: values.description,
          position: values.position,
        },
        expectedUpdatedAt: editing.updated_at,
      },
      { onSuccess: () => setEditing(null) },
    );

  const columns = [
    { title: 'Collection', dataIndex: 'name' },
    {
      title: 'Slug',
      dataIndex: 'slug',
      render: (value) => <Typography.Text code>{value}</Typography.Text>,
    },
    {
      title: 'List ID',
      dataIndex: 'list_id',
      render: (value) => <Typography.Text code>{value}</Typography.Text>,
    },
    { title: 'Products', dataIndex: 'product_count' },
    {
      title: 'Status',
      dataIndex: 'is_active',
      render: (value) => (
        <Tag color={value ? 'green' : 'default'}>{value ? 'visible' : 'hidden'}</Tag>
      ),
    },
    {
      title: '',
      key: 'actions',
      render: (_, row) => (
        <Space>
          <Button
            size="small"
            onClick={() => {
              setEditing(row);
              editForm.setFieldsValue(row);
            }}
          >
            Edit
          </Button>
          <Button size="small" onClick={() => setChoosing(row)}>
            Products
          </Button>
          <Button size="small" onClick={() => setTranslating(row)}>
            Languages
          </Button>
          <Button size="small" onClick={() => toggleActive(row)}>
            {row.is_active ? 'Hide' : 'Show'}
          </Button>
        </Space>
      ),
    },
  ];

  return (
    <>
      <PageHeader
        title="Collections"
        extra={
          <Button type="primary" onClick={() => setCreating(true)}>
            New collection
          </Button>
        }
      />

      {update.isError ? (
        <Alert type="error" showIcon message={update.error.message} className={styles.alert} />
      ) : null}

      <Table
        rowKey="id"
        loading={isPending}
        columns={columns}
        dataSource={collections}
        pagination={false}
      />

      <Modal
        open={creating}
        title="New collection"
        okText="Create collection"
        confirmLoading={create.isPending}
        onCancel={() => setCreating(false)}
        onOk={() => createForm.submit()}
        destroyOnHidden
      >
        {create.isError ? (
          <Alert type="error" showIcon message={create.error.message} className={styles.alert} />
        ) : null}

        <Form form={createForm} layout="vertical" requiredMark={false} onFinish={onCreate}>
          <Form.Item
            label="Name"
            name="name"
            rules={[{ required: true, message: 'Give the collection a name' }]}
          >
            <Input aria-label="Name" placeholder="Summer Edit" />
          </Form.Item>
          <Form.Item label="Slug" name="slug" help="Defaults from the name.">
            <Input aria-label="Slug" placeholder="summer-edit" />
          </Form.Item>
          <Form.Item
            label="List ID"
            name="list_id"
            help="Reporting identifier. Lowercase, digits and underscores."
          >
            <Input aria-label="List ID" placeholder="summer_edit" />
          </Form.Item>
          <Form.Item label="Description" name="description">
            <Input.TextArea aria-label="Description" rows={2} />
          </Form.Item>
          <Form.Item label="Position" name="position">
            <InputNumber aria-label="Position" min={0} />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        open={editing != null}
        title={editing ? `Edit ${editing.name}` : 'Edit'}
        okText="Save changes"
        confirmLoading={update.isPending}
        onCancel={() => setEditing(null)}
        onOk={() => editForm.submit()}
        destroyOnHidden
      >
        <Form form={editForm} layout="vertical" requiredMark={false} onFinish={onEdit}>
          <Form.Item
            label="Name"
            name="name"
            rules={[{ required: true, message: 'Give the collection a name' }]}
          >
            <Input aria-label="Name" />
          </Form.Item>
          <Form.Item label="Slug" name="slug">
            <Input aria-label="Slug" />
          </Form.Item>
          <Form.Item label="List ID" name="list_id">
            <Input aria-label="List ID" />
          </Form.Item>
          <Form.Item label="Description" name="description">
            <Input.TextArea aria-label="Description" rows={2} />
          </Form.Item>
          <Form.Item label="Position" name="position">
            <InputNumber aria-label="Position" min={0} />
          </Form.Item>
        </Form>
      </Modal>

      {choosing ? (
        <MembersModal
          key={choosing.id}
          open
          name={choosing.name}
          memberIds={members.data ?? []}
          products={products}
          loading={members.isPending}
          saving={setProducts.isPending}
          error={setProducts.isError ? setProducts.error : null}
          onClose={() => setChoosing(null)}
          onSave={(productIds) =>
            setProducts.mutate(
              { collectionId: choosing.id, productIds },
              { onSuccess: () => setChoosing(null) },
            )
          }
        />
      ) : null}

      {translating ? (
        <TranslationsModal
          key={translating.id}
          open
          name={translating.name}
          translations={translating.translations}
          saving={translate.isPending}
          error={translate.isError ? translate.error : null}
          onClose={() => setTranslating(null)}
          onSave={(locale, values) =>
            translate.mutate(
              { collectionId: translating.id, locale, values },
              { onSuccess: () => setTranslating(null) },
            )
          }
        />
      ) : null}
    </>
  );
}
