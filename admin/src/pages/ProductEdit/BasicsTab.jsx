import { Alert, Button, Form, Input, Select, Space } from 'antd';

import { useCategories } from '../../hooks/useCategories.js';
import { useUpdateProduct } from '../../hooks/useProduct.js';
import { AGE_GROUPS, CONDITIONS, GENDERS } from '../../utils/constants.js';
import styles from './ProductEdit.module.scss';

const asOptions = (values) => values.map((value) => ({ value, label: value }));

/**
 * The non-translated fields.
 *
 * Status is not here: publishing and archiving are their own operations with
 * their own preconditions, and a status dropdown would imply an operator can
 * move a product to `active` without the variants and content that state
 * requires.
 */
export default function BasicsTab({ product }) {
  const [form] = Form.useForm();
  const { data: categories = [] } = useCategories();
  const save = useUpdateProduct(product.id);

  const options = categories.map((category) => ({
    value: category.id,
    label: `${category.parent_name} / ${category.name}${category.is_active ? '' : ' (inactive)'}`,
  }));

  const onFinish = (values) => {
    save.mutate(values, {
      onError: (error) => {
        const fields = [];
        if (error.status === 409) fields.push({ name: 'slug', errors: [error.message] });
        for (const [name, message] of Object.entries(error.fieldErrors ?? {})) {
          fields.push({ name, errors: [message] });
        }
        if (fields.length > 0) form.setFields(fields);
      },
    });
  };

  return (
    <Form
      form={form}
      layout="vertical"
      requiredMark={false}
      className={styles.form}
      initialValues={{
        title: product.title,
        slug: product.slug,
        brand: product.brand,
        category_id: product.category_id,
        description: product.description ?? '',
        condition: product.condition ?? undefined,
        gender: product.gender ?? undefined,
        age_group: product.age_group ?? undefined,
        tags: product.tags ?? [],
      }}
      onFinish={onFinish}
    >
      {save.isError && Object.keys(save.error.fieldErrors ?? {}).length === 0 ? (
        <Alert type="error" showIcon message={save.error.message} className={styles.alert} />
      ) : null}
      {save.isSuccess ? (
        <Alert type="success" showIcon message="Saved." className={styles.alert} />
      ) : null}

      <Form.Item
        label="Title"
        name="title"
        rules={[{ required: true, message: 'Title is required' }]}
      >
        <Input />
      </Form.Item>

      <Form.Item
        label="Slug"
        name="slug"
        rules={[{ required: true, message: 'Slug is required' }]}
        extra="The base URL segment. Renaming a published product writes a 301 from the old path."
      >
        <Input />
      </Form.Item>

      <Form.Item label="Category" name="category_id">
        <Select
          aria-label="Category"
          options={options}
          showSearch
          optionFilterProp="label"
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

      <Form.Item label="Tags" name="tags">
        <Select aria-label="Tags" mode="tags" tokenSeparators={[',']} />
      </Form.Item>

      <Button type="primary" htmlType="submit" loading={save.isPending}>
        Save changes
      </Button>
    </Form>
  );
}
