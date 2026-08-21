import { Alert, Form, Input, Modal, Radio, Space, Switch, Tag } from 'antd';
import { useEffect, useState } from 'react';

import { LOCALES } from '../../../utils/constants.js';

const EMPTY = {
  title: '',
  slug: '',
  description: '',
  meta_description: '',
  is_published: false,
};

const labelFor = (code) => LOCALES.find((locale) => locale.code === code)?.label ?? code;

/**
 * One language's name, slug and SEO copy — for a category or a collection.
 *
 * Shared between both because the payload is literally the same
 * (`admin_translation_upsert`), and two copies of a form whose fields must
 * agree with one schema is two places for them to stop agreeing.
 *
 * **Per-language publishing is the locked decision.** English can be live while
 * Arabic is still being written, so this edits exactly one locale at a time and
 * every action names it — "Save Arabic", never "Save". An operator who cannot
 * tell which language a button affects will eventually publish an empty one.
 *
 * The storefront resolves a category URL through this row, so a category with
 * no translation in a locale is simply absent from that language's menu. That
 * is why an unwritten language says "not started" rather than showing the other
 * language's text greyed out: it is genuinely missing, not merely unedited.
 */
export default function TranslationsModal({
  open,
  name,
  translations = [],
  onSave,
  onClose,
  saving = false,
  error = null,
}) {
  const [form] = Form.useForm();
  const [locale, setLocale] = useState(LOCALES[0].code);

  const translation = translations.find((entry) => entry.locale === locale);
  const direction = LOCALES.find((entry) => entry.code === locale)?.dir ?? 'ltr';

  // Switching language swaps the whole form. Without this the fields keep the
  // previous locale's values and saving writes English into Arabic.
  useEffect(() => {
    form.setFieldsValue({ ...EMPTY, ...(translation ?? {}) });
  }, [form, locale, translation, open]);

  const textProps = { dir: direction, lang: locale };

  return (
    <Modal
      open={open}
      title={`Languages — ${name}`}
      okText={`Save ${labelFor(locale)}`}
      confirmLoading={saving}
      onCancel={onClose}
      onOk={() => form.submit()}
      destroyOnHidden
    >
      <Space size="middle" wrap style={{ marginBottom: 16 }}>
        <Radio.Group
          value={locale}
          onChange={(event) => setLocale(event.target.value)}
          options={LOCALES.map(({ code, label }) => ({ value: code, label }))}
          optionType="button"
        />
        {translation ? (
          <Tag color={translation.is_published ? 'green' : 'default'}>
            {translation.is_published ? 'published' : 'draft'}
          </Tag>
        ) : (
          <Tag>not started</Tag>
        )}
      </Space>

      {error ? (
        <Alert type="error" showIcon message={error.message} style={{ marginBottom: 16 }} />
      ) : null}

      <Form
        form={form}
        layout="vertical"
        requiredMark={false}
        onFinish={(values) => onSave(locale, values)}
      >
        <Form.Item
          label="Title"
          name="title"
          rules={[{ required: true, message: `A title is required to save ${labelFor(locale)}` }]}
        >
          <Input aria-label="Title" {...textProps} />
        </Form.Item>

        <Form.Item
          label="Slug"
          name="slug"
          help="The URL this language is reached at. Changing it changes the address."
        >
          <Input aria-label="Slug" {...textProps} />
        </Form.Item>

        <Form.Item label="Description" name="description">
          <Input.TextArea aria-label="Description" rows={3} {...textProps} />
        </Form.Item>

        <Form.Item label="Meta description" name="meta_description">
          <Input.TextArea aria-label="Meta description" rows={2} {...textProps} />
        </Form.Item>

        <Form.Item label="Published" name="is_published" valuePropName="checked">
          <Switch aria-label="Published" />
        </Form.Item>
      </Form>
    </Modal>
  );
}
