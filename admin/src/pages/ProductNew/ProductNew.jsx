import { useMutation } from '@tanstack/react-query';
import { Alert, Button, Card, Form, Input, Select, Space } from 'antd';
import { useRef } from 'react';
import { useNavigate } from 'react-router-dom';

import PageHeader from '../../components/common/PageHeader/PageHeader.jsx';
import { useCategories } from '../../hooks/useCategories.js';
import { createProduct } from '../../services/catalog.service.js';
import { AGE_GROUPS, CONDITIONS, GENDERS } from '../../utils/constants.js';
import { slugify } from '../../utils/slugify.js';
import styles from './ProductNew.module.scss';

const asOptions = (values) => values.map((value) => ({ value, label: value }));

/**
 * Create a product in draft. Nothing here publishes anything.
 *
 * Only the fields the API requires plus the ones a Merchant Center feed needs
 * on every offer. Content, variants and publishing are the editor's job — a
 * create form that tried to do all of it would be a form nobody finishes.
 */
export default function ProductNew() {
  const [form] = Form.useForm();
  const navigate = useNavigate();
  const { data: categories = [], isPending: loadingCategories } = useCategories();
  // Once the operator types a slug, the title stops driving it. The slug is the
  // URL; silently rewriting a chosen one because the title was corrected later
  // is how a product ends up at an address nobody meant.
  const slugTouched = useRef(false);

  const create = useMutation({
    mutationFn: createProduct,
    onSuccess: (product) => navigate(`/products/${product.id}`, { replace: true }),
    onError: (error) => {
      const fields = [];
      // 409 says which value collided but not which field; slug is the only
      // one this form lets the operator choose, so it is where it belongs.
      if (error.status === 409 && /slug/i.test(error.message)) {
        fields.push({ name: 'slug', errors: [error.message] });
      }
      if (error.status === 409 && /item group/i.test(error.message)) {
        fields.push({ name: 'item_group_id', errors: [error.message] });
      }
      for (const [name, message] of Object.entries(error.fieldErrors ?? {})) {
        fields.push({ name, errors: [message] });
      }
      if (fields.length > 0) form.setFields(fields);
    },
  });

  const options = categories.map((category) => ({
    value: category.id,
    label: `${category.parent_name} / ${category.name}${category.is_active ? '' : ' (inactive)'}`,
  }));

  const onTitleChange = (event) => {
    if (slugTouched.current) return;
    form.setFieldsValue({ slug: slugify(event.target.value) });
  };

  const showBanner =
    create.isError && Object.keys(create.error.fieldErrors ?? {}).length === 0 &&
    create.error.status !== 409;

  return (
    <>
      <PageHeader title="New product" />
      <Card className={styles.card}>
        {showBanner ? (
          <Alert
            type="error"
            showIcon
            message={create.error.message}
            className={styles.alert}
          />
        ) : null}

        <Form
          form={form}
          layout="vertical"
          requiredMark={false}
          initialValues={{ brand: 'Pixi', condition: 'new' }}
          onFinish={(values) => create.mutate(values)}
        >
          <Form.Item
            label="Title"
            name="title"
            rules={[{ required: true, message: 'Title is required' }]}
          >
            <Input onChange={onTitleChange} autoFocus />
          </Form.Item>

          <Form.Item
            label="Slug"
            name="slug"
            rules={[{ required: true, message: 'Slug is required' }]}
            extra="Lower-case ASCII, digits and single hyphens. This is the URL."
          >
            <Input onChange={() => { slugTouched.current = true; }} />
          </Form.Item>

          <Form.Item
            label="Category"
            name="category_id"
            rules={[{ required: true, message: 'Category is required' }]}
            extra="Products attach to level-2 categories only."
          >
            <Select
              aria-label="Category"
              loading={loadingCategories}
              options={options}
              showSearch
              optionFilterProp="label"
              placeholder="Choose a category"
            />
          </Form.Item>

          <Space size="middle" wrap className={styles.row}>
            <Form.Item label="Brand" name="brand" className={styles.field}>
              <Input />
            </Form.Item>
            <Form.Item label="Condition" name="condition" className={styles.field}>
              <Select aria-label="Condition" options={asOptions(CONDITIONS)} />
            </Form.Item>
            <Form.Item label="Gender" name="gender" className={styles.field}>
              <Select aria-label="Gender" allowClear options={asOptions(GENDERS)} />
            </Form.Item>
            <Form.Item label="Age group" name="age_group" className={styles.field}>
              <Select aria-label="Age group" allowClear options={asOptions(AGE_GROUPS)} />
            </Form.Item>
          </Space>

          <Form.Item label="Description" name="description">
            <Input.TextArea rows={4} />
          </Form.Item>

          <Form.Item
            label="Item group ID"
            name="item_group_id"
            rules={[{ max: 64, message: 'At most 64 characters' }]}
            extra="Merchant Center's variant-grouping key. Generated from the slug if left blank."
          >
            <Input />
          </Form.Item>

          <Button type="primary" htmlType="submit" loading={create.isPending}>
            Create product
          </Button>
        </Form>
      </Card>
    </>
  );
}
