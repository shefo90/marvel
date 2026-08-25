import { Alert, Button, Form, Input, InputNumber, Modal, Select, Space, Table, Tag, Typography } from 'antd';
import { useState } from 'react';

import PageHeader from '../../components/common/PageHeader/PageHeader.jsx';
import TranslationsModal from '../../components/taxonomy/TranslationsModal/TranslationsModal.jsx';
import { useCategoryMutations, useCategoryTree } from '../../hooks/useTaxonomy.js';
import styles from './Categories.module.scss';

/**
 * The category tree — the structure the shop is organised around.
 *
 * Until this screen existed the operator managed it with hand-written HTTP,
 * which is to say they did not manage it. The API has been complete since the
 * browse slice landed.
 *
 * **Nothing here deletes.** Products point at a category and historic cart and
 * order lines carry its `item_list_id`, so removing one would either be refused
 * by a foreign key or silently orphan the attribution section 5 exists to
 * preserve. `is_active` is the switch, exactly as it is for offers — and
 * inactive rows stay listed and flagged, because a category that disappears
 * from its own editor reads as deleted.
 *
 * **The parent is chosen at creation and never again.** Moving a category
 * between levels would change `products.category_level`, which is generated and
 * backs a composite foreign key, so every product in it would have to move too.
 * The API refuses it; the edit form simply does not offer it.
 */
export default function Categories() {
  const [createForm] = Form.useForm();
  const [editForm] = Form.useForm();
  const [creating, setCreating] = useState(false);
  const [editing, setEditing] = useState(null);
  // null means "the operator has not chosen yet", which is not the same as
  // "nothing is expanded" — see expandedKeys below.
  const [expanded, setExpanded] = useState(null);
  const [translating, setTranslating] = useState(null);

  const { data: tree = [], isPending } = useCategoryTree();
  const { create, update, translate } = useCategoryMutations();

  // Only level-1 categories may be parents: the tree is two deep by
  // construction, and a third level cannot be stored at all.
  const parents = tree.map((node) => ({ value: node.id, label: node.name }));

  // An empty children array still draws an expand arrow in AntD, which invites
  // the operator to open a row with nothing in it.
  const rows = tree.map((node) => ({
    ...node,
    children: node.children?.length ? node.children : undefined,
  }));

  // Expanded explicitly rather than with AntD's `defaultExpandAllRows`, which
  // reads the row set once when the Table mounts. The tree arrives from
  // react-query a tick later, so at mount there is nothing to expand and the
  // default silently applies to an empty list: the operator opens this screen
  // and every child category is hidden behind an arrow. Deriving the keys until
  // the operator collapses something themselves keeps the whole two-level tree
  // visible, which is the only reason to render it as a tree at all.
  const expandedKeys = expanded ?? rows.filter((row) => row.children).map((row) => row.id);

  const toggleActive = (row) =>
    update.mutate({
      categoryId: row.id,
      values: { is_active: !row.is_active },
      expectedUpdatedAt: row.updated_at,
    });

  const onCreate = (values) =>
    create.mutate(
      {
        name: values.name,
        parent_id: values.parent_id ?? null,
        slug: values.slug || undefined,
        list_id: values.list_id || undefined,
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
        categoryId: editing.id,
        values: {
          name: values.name,
          slug: values.slug,
          list_id: values.list_id,
          position: values.position,
        },
        expectedUpdatedAt: editing.updated_at,
      },
      { onSuccess: () => setEditing(null) },
    );

  const columns = [
    { title: 'Category', dataIndex: 'name' },
    {
      title: 'Slug',
      dataIndex: 'slug',
      render: (value) => <Typography.Text code>{value}</Typography.Text>,
    },
    {
      // Shown because it is section 5's item_list_id: it is stamped onto cart
      // and order lines, so an operator editing it is changing how this
      // category's traffic reports, not just a label.
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
        title="Categories"
        extra={
          <Button type="primary" onClick={() => setCreating(true)}>
            New category
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
        dataSource={rows}
        pagination={false}
        expandable={{ expandedRowKeys: expandedKeys, onExpandedRowsChange: setExpanded }}
      />

      <Modal
        open={creating}
        title="New category"
        okText="Create category"
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
            rules={[{ required: true, message: 'Give the category a name' }]}
          >
            <Input aria-label="Name" placeholder="Sandals" />
          </Form.Item>

          <Form.Item
            label="Parent"
            name="parent_id"
            help="Leave empty for a top-level category. This cannot be changed later."
          >
            <Select
              aria-label="Parent"
              allowClear
              options={parents}
              placeholder="None — top level"
            />
          </Form.Item>

          <Form.Item label="Slug" name="slug" help="Defaults from the name.">
            <Input aria-label="Slug" placeholder="sandals" />
          </Form.Item>

          <Form.Item
            label="List ID"
            name="list_id"
            help="Reporting identifier. Defaults from the slug; lowercase, digits and underscores."
          >
            <Input aria-label="List ID" placeholder="cat_sandals" />
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
            rules={[{ required: true, message: 'Give the category a name' }]}
          >
            <Input aria-label="Name" />
          </Form.Item>
          <Form.Item label="Slug" name="slug">
            <Input aria-label="Slug" />
          </Form.Item>
          <Form.Item label="List ID" name="list_id">
            <Input aria-label="List ID" />
          </Form.Item>
          <Form.Item label="Position" name="position">
            <InputNumber aria-label="Position" min={0} />
          </Form.Item>
        </Form>
      </Modal>

      {/* Keyed by id so switching categories remounts the form rather than
          leaving the previous category's copy in the fields. */}
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
              { categoryId: translating.id, locale, values },
              { onSuccess: () => setTranslating(null) },
            )
          }
        />
      ) : null}
    </>
  );
}
